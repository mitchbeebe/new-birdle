"""Premium gating and the thin Stripe wrappers the views/webhook use."""

import logging
from functools import wraps

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import Membership

logger = logging.getLogger(__name__)


def is_premium(user) -> bool:
    if not user.is_authenticated:
        return False
    membership = Membership.objects.filter(user=user).first()
    return membership is not None and membership.is_active


def premium_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_premium(request.user):
            return redirect("premium")
        return view(request, *args, **kwargs)

    return wrapper


# Stripe helpers. api_key is set at call time so importing without keys is fine.


def _configure():
    stripe.api_key = settings.STRIPE_SECRET_KEY


def create_customer(user) -> str:
    _configure()
    customer = stripe.Customer.create(email=user.email, metadata={"user_id": str(user.id)})
    return customer.id


def create_checkout_session(customer_id, user_id, success_url, cancel_url) -> str:
    _configure()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
        allow_promotion_codes=True,
        client_reference_id=str(user_id),
        success_url=success_url,
        cancel_url=cancel_url,
    )
    assert session.url is not None
    return session.url


def create_portal_session(customer_id, return_url) -> str:
    _configure()
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    assert session.url is not None
    return session.url


def construct_event(payload, sig_header):
    return stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
