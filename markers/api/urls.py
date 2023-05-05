from django.urls import path
from markers.api import views

urlpatterns = [
    path('observations/', views.ObservationListCreate.as_view(), name='observation_list_create'),
]