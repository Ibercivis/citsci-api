from django.urls import path
from markers.api import views

urlpatterns = [
    path('observations/', views.ObservationListCreate.as_view(), name='observation_list_create'),
    path('observations/<int:pk>/', views.ObservationRetrieveUpdateDestroy.as_view(), name='observation_retrieve'),
    path('field_form/<int:field_form_id>/observations/', views.ObservationByFieldFormList.as_view(), name='observation_by_field_form_list'),
    path('project/<int:project_id>/download_observations/', views.DownloadObservationsCSV.as_view(), name='download_observations_csv'),
]