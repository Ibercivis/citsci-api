from django.urls import path

from stats.api import views

urlpatterns = [
    path('stats/platform/', views.PlatformStatsView.as_view(), name='stats_platform'),
]
