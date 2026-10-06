from rest_framework import routers
from django.urls import path
from . import views
from .home import HomeContinueView, ManageProjectsView, MyImpactView, MyPendingCountView
from django.conf import settings
from django.conf.urls.static import static
from .views import (
    TopicsViewSet, HasTagViewSet, ProjectCreateViewSet, ValidateProjectPasswordView,
    MyLikedProjectsView, MyParticipatingProjectsView,
    ProjectInviteView, ProjectInvitationsListView,
    ProjectPendingInvitationsView, ProjectAcceptInvitationView, ProjectRejectInvitationView,
    ProjectCancelInvitationView, ProjectRemoveAdministratorView, ProjectExportView,
    RegenerateAnonymousTokenView,
)


router = routers.SimpleRouter()
router.register(r'project/topics', TopicsViewSet, basename='project-topics')
router.register(r'project/hastag', HasTagViewSet, basename='project-hastag')

urlpatterns = [
    path('project/create/', ProjectCreateViewSet.as_view(), name='project-create'),
    # JORGE: Me he llevado estas rutas a la aplicación de usuarios
    # path('users/', UserViewSet.as_view(), name='users'),
    # path('users/<int:pk>/', UserViewSetDetail.as_view(), name='users-detail'),

    # Rutas añadidas por Jorge, pendiente de revisar las anteriores y eliminarlas si no se usan 
    
    # Rutas de solo lectura para las pantallas de Inicio y Gestionar del front React (ver project/api/home.py)
    path('home/continue/', HomeContinueView.as_view(), name='home-continue'),
    path('manage/projects/', ManageProjectsView.as_view(), name='manage-projects'),
    path('users/me/impact/', MyImpactView.as_view(), name='my-impact'),
    path('users/me/pending-count/', MyPendingCountView.as_view(), name='my-pending-count'),
    path('project/', views.ProjectListCreate.as_view(), name='project_list_create'),    path('project/my_projects/', views.MyProjectsView.as_view(), name='my_projects'),
    path('project/my_admin_projects/', views.MyAdminProjectsView.as_view(), name='my_admin_projects'),
    path('project/drafts/', views.MyDraftProjectsView.as_view(), name='draft_projects'),
    path('project/my_liked/', views.MyLikedProjectsView.as_view(), name='my_liked_projects'),
    path('project/my_participating/', views.MyParticipatingProjectsView.as_view(), name='my_participating_projects'),
    path('project/<int:pk>/', views.ProjectRetrieveUpdateDestroy.as_view(), name='project_retrieve_update_destroy'),
    path('projects/<int:project_id>/toggle-like/', views.toggle_project_like, name='toggle_project_like'),
    path('projects/<int:project_id>/validate-password/', ValidateProjectPasswordView.as_view(), name='validate-project-password'),
    
    path('project/<int:pk>/email-intro/', views.ProjectEmailIntroView.as_view(), name='project_email_intro'),
    path('project/countries/', views.ProjectCountriesView.as_view(), name='project-countries'),

    path('project/<int:pk>/administrators/<int:user_id>/', ProjectRemoveAdministratorView.as_view(), name='project-remove-administrator'),

    # Project invitations
    path('project/<int:project_id>/invite/', ProjectInviteView.as_view(), name='project-invite'),
    path('project/<int:project_id>/invitations/', ProjectInvitationsListView.as_view(), name='project-invitations-list'),
    path('project/invitations/pending/', ProjectPendingInvitationsView.as_view(), name='project-invitations-pending'),
    path('project/invitations/<int:invitation_id>/accept/', ProjectAcceptInvitationView.as_view(), name='project-invitation-accept'),
    path('project/invitations/<int:invitation_id>/reject/', ProjectRejectInvitationView.as_view(), name='project-invitation-reject'),
    path('project/invitations/<int:invitation_id>/cancel/', ProjectCancelInvitationView.as_view(), name='project-invitation-cancel'),

    path('project/<int:pk>/export/', ProjectExportView.as_view(), name='project-export'),
    path('project/<int:pk>/regenerate-anonymous-token/', RegenerateAnonymousTokenView.as_view(), name='project-regenerate-anonymous-token'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += router.urls