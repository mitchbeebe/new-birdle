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
from django.conf.urls import handler404, handler500

urlpatterns = [
    path('', views.daily_bird, name='daily_bird'),
    path('stats/', views.stats, name='stats'),
    path('help/', views.help, name='help'),
    path('about/', views.about, name='about'),
    path('practice/', views.practice, name='practice'),
    path('practice/<str:region>/<str:family>', views.practice, name='practice-region-family'),
    path('api/birds/', views.bird_autocomplete, name='bird_autocomplete'),
    path("region", views.region),
    path("admin/", admin.site.urls)
]

handler404 = "birdle.views.error_404"
handler500 = "birdle.views.error_500"