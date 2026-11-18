# Development image for the API. Not the production one: production runs on the host under
# supervisord (see deploy.sh), and this does not change that. What it solves is that the repository
# had no way to start the API locally at all.
#
# Python 3.11 and no later: it is the newest version with a wheel for every pin in
# requirements.txt, h3==3.7.7 included. glibc and not Alpine: GDAL and the scientific wheels do not
# build on musl.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# GDAL/GEOS/PROJ, which is what django.contrib.gis.db.backends.postgis pulls in.
#
# Runtime libraries only, not the -dev packages and not gdal-bin: those take the image from 558 MB
# to 1.12 GB and buy nothing. Their unversioned symlinks are not needed either —
# django.contrib.gis reads GDAL_LIBRARY_PATH from the settings rather than the environment, so it
# cannot be pointed at a soname from outside, but ctypes.util.find_library() finds the versioned
# ones in the ldconfig cache. Checked inside this image: GEOS 3.11.1, GDAL 3.6.2, and PROJ
# resolving EPSG:4326.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgdal32 \
      libgeos-c1v5 \
      libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Its own layer, before the code, so a code change does not reinstall the dependencies.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

EXPOSE 8000

# The development server by default. compose.yaml overrides this command to start the worker and
# the scheduler.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
