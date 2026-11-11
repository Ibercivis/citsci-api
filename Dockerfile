# Imagen de DESARROLLO del API. No es la de produccion: produccion corre sobre el host con
# supervisord (ver deploy.sh), y esto no lo cambia. Lo que resuelve es que este repo no tenia
# ninguna forma de arrancarlo en local, ni para federar nada ni para mirarlo.
#
# Python 3.11 y no otra: es la version mas nueva para la que existe rueda de TODOS los pines de
# requirements.txt, h3==3.7.7 incluido. Y glibc, no Alpine: GDAL y las ruedas cientificas no se
# compilan en musl, y los nombres de red bajo .localhost no se resuelven igual.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# GDAL/GEOS/PROJ, que es lo que arrastra django.contrib.gis.db.backends.postgis.
#
# Van las librerias de runtime y NO los paquetes -dev ni gdal-bin: con los -dev la imagen pasa de
# 558 MB a 1,12 GB sin ganar nada. La duda era si hacian falta sus enlaces sin version, porque
# django.contrib.gis lee GDAL_LIBRARY_PATH de los settings y no del entorno, asi que no se le puede
# apuntar a un soname desde fuera; pero ctypes.util.find_library() encuentra los versionados en el
# cache de ldconfig. Comprobado dentro de esta imagen: GEOS 3.11.1, GDAL 3.6.2 y PROJ resolviendo
# el EPSG:4326.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgdal32 \
      libgeos-c1v5 \
      libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# En capa propia y antes del codigo, para que un cambio en el codigo no reinstale las dependencias.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

EXPOSE 8000

# Por defecto, el servidor de desarrollo. El worker y el scheduler son los mismos de supervisord y
# los lanza compose.yaml cambiando este command.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
