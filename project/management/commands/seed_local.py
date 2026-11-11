"""
Seed a small local dataset for development.

**Nothing is copied from production, and nothing needs to be.** The dataset has
two halves, and only one of them is real:

* **The observations are real public records.** Species, coordinates and dates
  come from `local_dev/gbif_sample.json`, a committed snapshot of GBIF
  occurrence records published under CC0. `local_dev/fetch_gbif_sample.py` built
  it, and it keeps an allow-list of fields: the name of whoever made each
  observation is never fetched, so no personal data reaches this repository.

* **Every person is invented.** The accounts, their names, their addresses (all
  on the reserved `.invalid` domain, so none of them can receive mail), their
  profiles and the organization are made up here. The photographs are drawn by
  this command, and look drawn on purpose.

That split is the point: in this application the only personal data lives in
`auth_user`, `account_emailaddress` and `users_profile`. Projects, field forms
and observations carry none — so the half of a development dataset that should
be realistic is exactly the half that can be rebuilt from a public source, and
the half that would have carried personal data is the half that is cheapest to
invent. There is nothing to anonymise because nothing is copied.

Usage:

    python manage.py seed_local
    python manage.py seed_local --observations 120
    python manage.py seed_local --no-images
    python manage.py seed_local --reset
"""
# pylint: disable=too-many-locals,too-many-statements,too-many-instance-attributes

import io
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from hashlib import md5

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.contrib.sites.models import Site
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from field_forms.models import FieldForm, Question
from markers.models import (
    Observation,
    ObservationFieldValue,
    ObservationImage,
    ProjectObservationField,
)
from organizations.models import Organization, Type
from project.models import (
    HasTag,
    Project,
    ProjectCover,
    ProjectMembership,
    ProjectStatusLog,
    Topic,
)
from users.models import Profile

SNAPSHOT = os.path.join(settings.BASE_DIR, "local_dev", "gbif_sample.json")

# RFC 2606 reserves `.invalid`, so none of these addresses can ever resolve.
EMAIL_DOMAIN = "geonity.invalid"

PASSWORD = "devpass12345"

# Invented people. handle, first, last, country, biography
SUPERUSER = ("admin", "Local", "Admin", "ES", "Invented superuser, local development only.")
STEWARD = (
    "rosa",
    "Rosa",
    "Villanueva",
    "ES",
    "Invented account. Creates and administers the sample projects.",
)
VOLUNTEERS = [
    ("ada", "Ada", "Monegros", "ES", "Invented volunteer from Zaragoza."),
    ("bruno", "Bruno", "Estrada", "PT", "Invented volunteer from Porto."),
    ("chiara", "Chiara", "Luce", "IT", "Invented volunteer from Bologna."),
    ("dani", "Dani", "Aliaga", "ES", "Invented volunteer from Teruel."),
]

ORGANIZATION = "Observatorio Ciudadano del Ebro"


def localized(spanish, english):
    """The shape the API uses for translatable content."""
    return {"es": spanish, "en": english}


class Command(BaseCommand):
    """Create a small, entirely local development dataset."""

    help = (
        "Seed a small local dataset: invented accounts and organizations plus real "
        "CC0 species records from GBIF. Copies nothing from production."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--observations",
            type=int,
            default=60,
            help="Observations across the two published projects. Default 60.",
        )
        parser.add_argument(
            "--dates",
            choices=["shifted", "real"],
            default="shifted",
            help=(
                "GBIF publishes with a lag, so its newest record is about a month "
                "old. 'shifted' (the default) slides the whole set forward as a "
                "block, keeping the real intervals, so the newest observation is "
                "today and the screens that count 'this month' have something to "
                "count. 'real' keeps GBIF's own dates."
            ),
        )
        parser.add_argument(
            "--password",
            default=PASSWORD,
            help=f"Password for every seeded account. Default {PASSWORD!r}.",
        )
        parser.add_argument(
            "--no-images",
            action="store_true",
            help="Skip the drawn placeholder photographs (faster, emptier screens).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete what a previous run created, then stop.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip the check that refuses to run against a populated database.",
        )

    # --------------------------------------------------------------- lifecycle

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to run with DEBUG=False. This command writes invented "
                "accounts and is for local development only."
            )
        self._guard(options["force"])

        if options["reset"]:
            self._reset()
            return

        snapshot = self._load_snapshot()
        self.images = not options["no_images"]
        self.shift = self._shift(snapshot) if options["dates"] == "shifted" else timedelta()
        random.seed(20261111)  # the same dataset run after run

        with transaction.atomic():
            self._ensure_site()
            self._ensure_catalogues()
            admin = self._person(*SUPERUSER, options["password"], is_staff=True, is_superuser=True)
            steward = self._person(*STEWARD, options["password"], is_staff=True)
            volunteers = [
                self._person(*person, options["password"]) for person in VOLUNTEERS
            ]
            organization = self._organization(steward, volunteers)

            birds = self._project(
                steward,
                organization,
                volunteers,
                name="Aves del valle del Ebro",
                description=localized(
                    "Censo ciudadano de aves en el valle medio del Ebro: qué especie, "
                    "cuántos ejemplares y en qué ambiente. Datos de muestra para "
                    "desarrollo local.",
                    "Citizen bird census in the middle Ebro valley: which species, how "
                    "many individuals, and in what habitat. Sample data for local "
                    "development.",
                ),
                topics=["Biodiversidad", "Ecología y Medio Ambiente"],
                tags=["Suitable for children", "Participate from home"],
                is_global=False,
                countries=["ES"],
                anonymous_contribution=True,
            )
            moths = self._project(
                steward,
                organization,
                volunteers,
                name="Mariposas y polillas de España",
                description=localized(
                    "Observaciones de lepidópteros en toda España, con fotografía y fase "
                    "de desarrollo. Datos de muestra para desarrollo local.",
                    "Lepidoptera records across Spain, with a photograph and the life "
                    "stage. Sample data for local development.",
                ),
                topics=["Biodiversidad", "Biología"],
                tags=["Do-it-yourself"],
                is_global=True,
                countries=[],
                anonymous_contribution=False,
                fuzzy=True,
            )
            fresh = self._project(
                steward,
                organization,
                volunteers,
                name="Flora de ribera del Gállego",
                description=localized(
                    "Recién publicado y todavía sin observaciones: sirve para ver las "
                    "pantallas vacías y para que «Descubre proyectos» tenga algo que "
                    "ofrecer a quien ya participa en los demás.",
                    "Just published and still empty: it is what the empty-state screens "
                    "need, and what «Discover projects» has to offer somebody who is "
                    "already contributing to the others.",
                ),
                topics=["Biodiversidad", "Educación"],
                tags=["Teaching materials available"],
                is_global=False,
                countries=["ES"],
                anonymous_contribution=False,
                members=[],
            )
            draft = self._project(
                steward,
                organization,
                volunteers,
                name="Anfibios en balsas de riego",
                description=localized(
                    "Borrador: seguimiento de anfibios en balsas de riego. Sin publicar, "
                    "para ver las pantallas de borradores.",
                    "Draft: amphibians in irrigation ponds. Unpublished on purpose, so the "
                    "draft screens have something to show.",
                ),
                topics=["Biodiversidad"],
                tags=[],
                is_global=False,
                countries=["ES"],
                anonymous_contribution=False,
                draft=True,
            )

            half = max(1, options["observations"] // 2)
            birds_records = snapshot["themes"]["birds-ebro"]["records"][:half]
            moths_records = snapshot["themes"]["lepidoptera-spain"]["records"][
                : options["observations"] - half
            ]

            self._bird_form(birds, birds_records)
            self._moth_form(moths, moths_records)
            self._riverside_form(fresh)
            self._amphibian_form(draft)

            made = self._observations(birds, birds_records, volunteers, anonymous=True)
            made += self._observations(moths, moths_records, volunteers, anonymous=False)
            self._admin_fields(birds, steward)

        self._report(
            admin, steward, volunteers, [birds, moths, fresh, draft], made, options["password"]
        )

    def _guard(self, force):
        """Refuse to touch a database that holds accounts this command did not make."""
        strangers = User.objects.exclude(email__endswith=f"@{EMAIL_DOMAIN}").count()
        if strangers > 5 and not force:
            raise CommandError(
                f"This database holds {strangers} accounts that are not seeded ones. "
                "That does not look like a throwaway local database, so nothing was "
                "written. Pass --force if you are sure."
            )

    def _shift(self, snapshot):
        """How far forward to slide every date so the newest one lands today."""
        newest = max(
            self._parse(record["eventDate"])
            for theme in snapshot["themes"].values()
            for record in theme["records"]
        )
        return timezone.now() - newest

    def _load_snapshot(self):
        try:
            with open(SNAPSHOT, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as error:
            raise CommandError(
                f"{SNAPSHOT} is missing. Rebuild it with "
                "`python3 local_dev/fetch_gbif_sample.py`."
            ) from error

    # ------------------------------------------------------------------ setup

    def _ensure_site(self):
        """`migrate` leaves site 1 as example.com, which breaks the mail links."""
        site, _ = Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={"domain": "localhost:8000", "name": "Geonity (local)"},
        )
        self.stdout.write(f"Site {site.pk}: {site.domain}")

    def _ensure_catalogues(self):
        """Topics, tags and organization types ship as fixtures in this repository."""
        if not Topic.objects.exists():
            call_command("loaddata", "topics", verbosity=0)
        if not HasTag.objects.exists():
            call_command("loaddata", "hastag", verbosity=0)
        if not Type.objects.exists():
            call_command("loaddata", "type", verbosity=0)
        self.stdout.write(
            f"Catalogues: {Topic.objects.count()} topics, {HasTag.objects.count()} tags, "
            f"{Type.objects.count()} organization types"
        )

    # ----------------------------------------------------------------- people

    def _person(self, handle, first, last, country, biography, password, **flags):
        email = f"{handle}@{EMAIL_DOMAIN}"
        user, _ = User.objects.get_or_create(
            username=handle,
            defaults={"email": email, "first_name": first, "last_name": last},
        )
        user.email = email
        user.first_name = first
        user.last_name = last
        for key, value in flags.items():
            setattr(user, key, value)
        user.set_password(password)
        user.save()

        # The post_save signal already created the profile.
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.biography = biography
        profile.country = country
        profile.visibility = True
        profile.language = "es" if country == "ES" else "en"
        profile.terms_accepted_at = timezone.now() - timedelta(days=200)
        profile.terms_version = "local-sample"
        profile.privacy_accepted_at = profile.terms_accepted_at
        profile.privacy_version = "local-sample"
        if self.images and not profile.cover:
            profile.cover.save(
                f"{handle}-cover.jpg",
                self._drawn(f"{first} {last}", "perfil de muestra", (900, 300)),
                save=False,
            )
        profile.save()

        self._verified_email(user)
        self._token(user)
        self.stdout.write(f"  {email}")
        return user

    def _verified_email(self, user):
        """`ACCOUNT_EMAIL_VERIFICATION` is 'mandatory' and no mail is sent anywhere."""
        from allauth.account.models import EmailAddress  # noqa: PLC0415

        EmailAddress.objects.update_or_create(
            user=user,
            email=user.email,
            defaults={"verified": True, "primary": True},
        )

    def _token(self, user):
        """The API authenticates with DRF tokens, so hand one out up front."""
        from rest_framework.authtoken.models import Token  # noqa: PLC0415

        Token.objects.get_or_create(user=user)

    # ----------------------------------------------------------------- content

    def _organization(self, steward, volunteers):
        organization, _ = Organization.objects.update_or_create(
            principalName=ORGANIZATION,
            defaults={
                "url": "https://example.org/invented",
                "description": localized(
                    "Organización inventada para la muestra local. No existe.",
                    "Invented organization for the local sample. It does not exist.",
                ),
                "contactName": "Rosa Villanueva",
                "contactMail": f"rosa@{EMAIL_DOMAIN}",
                "countries": ["ES"],
                "is_global": False,
                "creator": steward,
            },
        )
        organization.type.set(Type.objects.filter(type="Académica")[:1] or Type.objects.all()[:1])
        organization.administrators.set([steward])
        organization.members.set(volunteers)
        if self.images and not organization.logo:
            organization.logo.save(
                "org-logo.jpg", self._drawn("OCE", "logo de muestra", (400, 400)), save=False
            )
        if self.images and not organization.cover:
            organization.cover.save(
                "org-cover.jpg",
                self._drawn(ORGANIZATION, "muestra local", (1200, 400)),
                save=False,
            )
        organization.save()
        self.stdout.write(f"Organization: {organization.principalName}")
        return organization

    def _project(self, steward, organization, volunteers, *, name, description, topics,
                 tags, is_global, countries, anonymous_contribution, draft=False,
                 fuzzy=False, members=None):
        created = timezone.now() - timedelta(days=240 if not draft else 20)
        project, _ = Project.objects.update_or_create(
            name=name,
            creator=steward,
            defaults={
                "created_at": created,
                "description": description,
                "is_private": False,
                "is_global": is_global,
                "countries": countries,
                "draft": draft,
                "public_map": not draft,
                # One project shows exact points and one aggregates into H3 cells, so
                # both map screens have something to draw.
                "fuzzy": fuzzy,
                "show_post_message": True,
                "post_observation_message": localized(
                    "¡Gracias! Tu observación ya está en el mapa.",
                    "Thank you! Your observation is on the map.",
                ),
                "email_on_observation": False,
                "email_monthly_stats": False,
                "anonymous_contribution": anonymous_contribution,
                "allowed_platforms": Project.PLATFORM_ALL,
                "published_at": None if draft else created + timedelta(days=2),
            },
        )
        project.administrators.set([steward])
        project.organizations.set([organization])
        project.topic.set(Topic.objects.filter(topic__in=topics))
        project.hasTag.set(HasTag.objects.filter(hasTag__in=tags))
        project.likes.set((volunteers if members is None else members)[:3])

        for volunteer in (volunteers if members is None else members):
            ProjectMembership.objects.get_or_create(project=project, user=volunteer)

        ProjectStatusLog.objects.filter(project=project).delete()
        ProjectStatusLog.objects.create(
            project=project, event=ProjectStatusLog.EVENT_CREATED, at=created, by=steward
        )
        if not draft:
            ProjectStatusLog.objects.create(
                project=project,
                event=ProjectStatusLog.EVENT_PUBLISHED,
                at=created + timedelta(days=2),
                by=steward,
            )

        if self.images and not project.covers.exists():
            cover = ProjectCover(project=project)
            cover.image.save(
                f"cover-{project.pk}.jpg",
                self._drawn(name, "portada de muestra", (1200, 600)),
                save=False,
            )
            cover.save()

        self.stdout.write(f"Project {project.pk}: {name}{' (draft)' if draft else ''}")
        return project

    # ------------------------------------------------------------- field forms

    def _form(self, project):
        form, _ = FieldForm.objects.get_or_create(project=project)
        form.questions.all().delete()
        return form

    def _bird_form(self, project, records):
        form = self._form(project)
        species = sorted({record["species"] for record in records})
        self._question(form, 0, localized("Especie", "Species"), Question.CHOICE,
                       mandatory=True, choices=species, allow_other=True,
                       help_text=localized("Nombre científico. Si no está en la lista, escríbelo.",
                                           "Scientific name. Not listed? Type it in."))
        self._question(form, 1, localized("Número de individuos", "Number of individuals"),
                       Question.NUMBER, mandatory=True)
        self._question(form, 2, localized("Fotografía", "Photograph"), Question.IMAGE)
        self._question(form, 3, localized("Ambiente", "Habitat"), Question.MULTICHOICE,
                       choices=[
                           {"value": "soto", "label": localized("Soto fluvial", "Riverside wood")},
                           {"value": "carrizal", "label": localized("Carrizal", "Reed bed")},
                           {"value": "regadio", "label": localized("Cultivo de regadío", "Irrigated crop")},
                           {"value": "urbano", "label": localized("Casco urbano", "Built-up area")},
                           {"value": "estepa", "label": localized("Estepa", "Steppe")},
                       ])
        self._question(form, 4, localized("Notas", "Notes"), Question.STRING)
        self.stdout.write(f"  Field form {form.pk}: 5 questions, {len(species)} species listed")
        return form

    def _moth_form(self, project, records):
        form = self._form(project)
        species = sorted({record["species"] for record in records})
        self._question(form, 0, localized("Especie", "Species"), Question.CHOICE,
                       mandatory=True, choices=species, allow_other=True)
        self._question(form, 1, localized("Fotografía", "Photograph"), Question.IMAGE)
        self._question(form, 2, localized("Fase", "Life stage"), Question.CHOICE,
                       mandatory=True,
                       choices=[
                           {"value": "adulto", "label": localized("Adulto", "Adult")},
                           {"value": "oruga", "label": localized("Oruga", "Caterpillar")},
                           {"value": "crisalida", "label": localized("Crisálida", "Pupa")},
                           {"value": "huevo", "label": localized("Huevo", "Egg")},
                       ])
        self._question(form, 3, localized("Fecha de la observación", "Date observed"), Question.DATE)
        self._question(form, 4, localized("Notas", "Notes"), Question.STRING)
        self.stdout.write(f"  Field form {form.pk}: 5 questions, {len(species)} species listed")
        return form

    def _amphibian_form(self, project):
        form = self._form(project)
        self._question(form, 0, localized("Especie", "Species"), Question.CHOICE, mandatory=True,
                       choices=["Pelophylax perezi", "Pelobates cultripes",
                                "Alytes obstetricans", "Bufo spinosus"], allow_other=True)
        self._question(form, 1, localized("Nivel de agua", "Water level"), Question.CHOICE,
                       choices=[
                           {"value": "lleno", "label": localized("Llena", "Full")},
                           {"value": "medio", "label": localized("A medias", "Half full")},
                           {"value": "seco", "label": localized("Seca", "Dry")},
                       ])
        self._question(form, 2, localized("Fotografía", "Photograph"), Question.IMAGE)
        self.stdout.write(f"  Field form {form.pk}: 3 questions (draft project, no observations)")
        return form

    def _riverside_form(self, project):
        form = self._form(project)
        self._question(form, 0, localized("Especie", "Species"), Question.CHOICE, mandatory=True,
                       choices=["Populus alba", "Salix alba", "Tamarix gallica",
                                "Fraxinus angustifolia", "Arundo donax"], allow_other=True)
        self._question(form, 1, localized("Fotografía", "Photograph"), Question.IMAGE)
        self._question(form, 2, localized("Notas", "Notes"), Question.STRING)
        self.stdout.write(f"  Field form {form.pk}: 3 questions (published, no observations yet)")
        return form

    def _question(self, form, order, text, answer_type, *, mandatory=False, choices=None,
                  allow_other=False, help_text=None):
        return Question.objects.create(
            field_form=form,
            question_text=text,
            question_help=help_text,
            answer_type=answer_type,
            mandatory=mandatory,
            order=order,
            choices=choices,
            allow_other=allow_other,
        )

    # ----------------------------------------------------------- observations

    def _observations(self, project, records, volunteers, *, anonymous):
        """One observation per public record, credited to an invented volunteer."""
        form = project.fieldform
        questions = {question.order: question for question in form.questions.all()}
        Observation.objects.filter(field_form=form).delete()

        made = 0
        latest = None
        for index, record in enumerate(records):
            when = self._timestamp(record)
            # Every fifth one is an anonymous QR contribution, where the project
            # allows them: no account, just the pseudonym the browser generated.
            is_anonymous = anonymous and index % 5 == 4
            observation = Observation(
                creator=None if is_anonymous else volunteers[index % len(volunteers)],
                field_form=form,
                timestamp=when,
                geoposition=Point(record["decimalLongitude"], record["decimalLatitude"]),
                data=self._answers(questions, record, when),
                platform=random.choice([Observation.PLATFORM_MOBILE, Observation.PLATFORM_WEB]),
                anonymous_id=uuid.uuid4() if is_anonymous else None,
                anonymous_source="qr" if is_anonymous else None,
            )
            observation.save()
            if self.images and Question.IMAGE in {q.answer_type for q in questions.values()}:
                image_question = next(
                    q for q in questions.values() if q.answer_type == Question.IMAGE
                )
                photo = ObservationImage(observation=observation, question=image_question)
                photo.image.save(
                    f"obs-{observation.pk}.jpg",
                    self._drawn(record["species"], "foto de muestra · no es una fotografía",
                                (800, 600)),
                    save=False,
                )
                photo.save()
            # `created_at` is auto_now_add, so every row would otherwise read as
            # created this minute and the activity feed would say "now" 60 times.
            # It has to be an UPDATE: a save() would overwrite it again.
            # Recorded a little after it was seen, but never in the future.
            recorded = min(timezone.now(), when + timedelta(minutes=random.randint(1, 240)))
            Observation.objects.filter(pk=observation.pk).update(
                created_at=recorded, updated_at=recorded
            )
            made += 1
            latest = when if latest is None or when > latest else latest

        Project.objects.filter(pk=project.pk).update(last_observation=latest)
        self.stdout.write(f"  {made} observations in '{project.name}'")
        return made

    def _parse(self, raw):
        raw = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = datetime.fromisoformat(raw[:10])
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed

    def _timestamp(self, record):
        return self._parse(record["eventDate"]) + self.shift

    def _answers(self, questions, record, when):
        """The `data` shape the API's own serializer accepts: a list of key/value pairs."""
        answers = []
        for order, question in sorted(questions.items()):
            if question.answer_type == Question.IMAGE:
                continue  # images are rows, not answers
            if question.answer_type == Question.CHOICE and order == 0:
                value = record["species"]
            elif question.answer_type == Question.CHOICE:
                value = random.choice([c["value"] for c in question.choices])
            elif question.answer_type == Question.MULTICHOICE:
                values = [c["value"] for c in question.choices]
                value = random.sample(values, random.randint(1, 2))
            elif question.answer_type == Question.NUMBER:
                value = random.randint(1, 14)
            elif question.answer_type == Question.DATE:
                value = when.date().isoformat()
            else:
                family = record.get("family", "—")
                iucn = record.get("iucnRedListCategory", "NE")
                uncertainty = record.get("coordinateUncertaintyInMeters")
                note = f"{family} · UICN {iucn}"
                if uncertainty:
                    note += f" · precisión ≈{int(uncertainty)} m"
                value = note
            answers.append({"key": str(question.pk), "value": value})
        return answers

    def _admin_fields(self, project, steward):
        """The administrative columns the admin panel edits, with some filled in."""
        ProjectObservationField.objects.filter(project=project).delete()
        validated = ProjectObservationField.objects.create(
            project=project, key="validated", label="Validada",
            field_type=ProjectObservationField.TYPE_BOOL, order=10, public=True,
            help_text="Revisada por el equipo del proyecto",
        )
        status = ProjectObservationField.objects.create(
            project=project, key="status", label="Estado",
            field_type=ProjectObservationField.TYPE_CHOICE, order=20,
            choices=["Recibida", "En revisión", "Aceptada", "Descartada"],
        )
        filled = 0
        for index, observation in enumerate(
            Observation.objects.filter(field_form__project=project).order_by("pk")
        ):
            if index % 3:
                continue
            ObservationFieldValue.objects.update_or_create(
                observation=observation, field=validated,
                defaults={"value": index % 2 == 0, "updated_by": steward},
            )
            ObservationFieldValue.objects.update_or_create(
                observation=observation, field=status,
                defaults={
                    "value": ["Recibida", "En revisión", "Aceptada"][index % 3],
                    "updated_by": steward,
                },
            )
            filled += 1
        self.stdout.write(f"  2 administrative columns, {filled} observations filled in")

    # -------------------------------------------------------------- placeholder

    # Debian ships these in the image; Pillow's built-in font has no accents.
    FONTS = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )

    def _font(self, size):
        from PIL import ImageFont  # noqa: PLC0415

        for candidate in self.FONTS:
            if os.path.exists(candidate):
                return ImageFont.truetype(candidate, size)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # very old Pillow
            return ImageFont.load_default()

    def _drawn(self, title, subtitle, size):
        """A drawn placeholder, not a photograph, and it should look like one.

        Observation photographs are the one part of the sample that cannot come
        from a public source: a real species photograph belongs to whoever took
        it. So these are generated, deterministic per title, and say on the
        image itself that they are not photographs.
        """
        from PIL import Image, ImageDraw  # noqa: PLC0415

        width, height = size
        digest = md5(title.encode("utf-8")).hexdigest()  # noqa: S324 — a colour, not a secret
        hue = tuple(60 + int(digest[i : i + 2], 16) % 130 for i in (0, 2, 4))
        canvas = Image.new("RGB", size, hue)
        draw = ImageDraw.Draw(canvas)

        stripe = tuple(max(0, channel - 26) for channel in hue)
        for step in range(0, width + height, max(14, width // 22)):
            draw.line([(step, 0), (0, step)], fill=stripe, width=3)

        band = height // 4
        draw.rectangle(
            [0, (height - band) // 2, width, (height + band) // 2],
            fill=tuple(max(0, channel - 60) for channel in hue),
        )

        # Shrink the title until it fits the width, rather than letting it run off.
        points = max(13, int(height / 7))
        font = self._font(points)
        while points > 11 and draw.textlength(title, font=font) > width * 0.88:
            points -= 2
            font = self._font(points)
        small = self._font(max(10, int(points * 0.42)))

        draw.text(
            (width / 2, height / 2 - points * 0.25),
            title,
            fill=(255, 255, 255),
            font=font,
            anchor="mm",
        )
        draw.text(
            (width / 2, height / 2 + points * 0.72),
            subtitle,
            fill=(236, 236, 236),
            font=small,
            anchor="mm",
        )

        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=72)
        return ContentFile(buffer.getvalue())

    # ------------------------------------------------------------------ reset

    def _reset(self):
        """Remove what this command created, and nothing else."""
        seeded = User.objects.filter(email__endswith=f"@{EMAIL_DOMAIN}")
        projects = Project.objects.filter(creator__in=seeded)
        counts = {
            "accounts": seeded.count(),
            "projects": projects.count(),
            "observations": Observation.objects.filter(field_form__project__in=projects).count(),
            "organizations": Organization.objects.filter(creator__in=seeded).count(),
        }
        # Project cascades to FieldForm, Question, Observation and its images.
        projects.delete()
        Organization.objects.filter(creator__in=seeded).delete()
        seeded.delete()
        self.stdout.write(
            self.style.SUCCESS(
                "Removed {accounts} invented account(s), {projects} project(s), "
                "{observations} observation(s) and {organizations} organization(s).".format(
                    **counts
                )
            )
        )
        self.stdout.write("Files under media/ were left alone, and so were topics and tags.")

    # ----------------------------------------------------------------- report

    def _report(self, admin, steward, volunteers, projects, observations, password):
        base = os.environ.get("LOCAL_BASE_URL", "http://localhost:8000")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Local dataset ready: {observations} observations."))
        self.stdout.write("")
        self.stdout.write(f"  API docs     {base}/api/docs/")
        self.stdout.write(f"  Django admin {base}/admin/")
        for project in projects:
            self.stdout.write(
                f"  Project {project.pk}    {project.name}"
                f"{' (draft)' if project.draft else ''}"
            )
        anonymous = projects[0].anonymous_token
        self.stdout.write(f"  Anonymous QR {base}/api/anonymous/{anonymous}/")
        self.stdout.write("")
        self.stdout.write(f"  Every account's password: {password}")
        self.stdout.write(f"  Superuser:   {admin.email}")
        self.stdout.write(f"  Owner/staff: {steward.email}")
        for volunteer in volunteers:
            self.stdout.write(f"  Volunteer:   {volunteer.email}")
        self.stdout.write("")
        self.stdout.write(
            "Species, coordinates and dates are CC0 records from GBIF. Accounts, "
            "organization and photographs are invented here. Nothing came from production."
        )
