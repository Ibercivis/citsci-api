from django.urls import path

from stats.api import views

urlpatterns = [
    path('stats/platform/', views.PlatformStatsView.as_view(), name='stats_platform'),
    path('stats/me/', views.MyStatsView.as_view(), name='stats_me'),
    path('project/<int:pk>/stats/', views.ProjectStatsView.as_view(), name='stats_project'),
]
