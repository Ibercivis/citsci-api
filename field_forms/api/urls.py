from django.urls import path
from . import views

urlpatterns = [
    path('field_forms/', views.FieldFormListCreate.as_view(), name='field_form_list_create'),
    path('field_forms/<int:pk>/', views.FieldFormRetrieveUpdateDestroy.as_view(), name='field_form_retrieve_update_destroy'),
    path('questions/', views.QuestionListCreate.as_view(), name='question_list_create'),
    path('questions/<int:pk>/', views.QuestionRetrieveUpdateDestroy.as_view(), name='question_retrieve_update_destroy'),
]