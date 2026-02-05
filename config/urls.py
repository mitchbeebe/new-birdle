"""birdle URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path
from django.contrib import admin
from birdle import views

urlpatterns = [
    # Default paths (without region in URL)
    path("", views.daily_bird, name="daily_bird"),
    path("stats/", views.stats, name="stats"),
    path("info/", views.info, name="info"),
    path("practice/", views.practice, name="practice"),
    path(
        "practice/<str:region>/<str:family>",
        views.practice,
        name="practice-region-family",
    ),
    path("api/birds/", views.bird_autocomplete, name="bird_autocomplete"),
    path("region", views.region),
    path("admin/", admin.site.urls),
    # Regional paths (with region code in URL) - after specific paths
    path("<str:region_code>/", views.daily_bird, name="daily_bird_region"),
    path("<str:region_code>/stats/", views.stats, name="stats_region"),
]

handler404 = "birdle.views.error_404"
handler500 = "birdle.views.error_500"
