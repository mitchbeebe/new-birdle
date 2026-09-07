"""Friendship queries and the send-request rule set."""

from django.db.models import Q

from .models import Friendship


def friend_ids(user) -> set[int]:
    """IDs of users with an accepted friendship with ``user``, in either direction."""
    rows = Friendship.objects.filter(
        Q(from_user=user) | Q(to_user=user), status=Friendship.ACCEPTED
    ).values_list("from_user_id", "to_user_id")
    return {other for pair in rows for other in pair if other != user.pk}


def pending_incoming(user):
    return Friendship.objects.filter(to_user=user, status=Friendship.PENDING).select_related(
        "from_user"
    )


def pending_outgoing(user):
    return Friendship.objects.filter(from_user=user, status=Friendship.PENDING).select_related(
        "to_user"
    )


def send_request(from_user, to_user) -> Friendship:
    """Create a pending request, or accept the reverse one if it is already pending.

    Raises ValueError for self-requests and when any friendship row already links the two
    users (pending in this direction, or already accepted in either direction).
    """
    if from_user.pk == to_user.pk:
        raise ValueError("You can't add yourself.")
    reverse = Friendship.objects.filter(from_user=to_user, to_user=from_user).first()
    if reverse is not None:
        if reverse.status == Friendship.PENDING:
            reverse.status = Friendship.ACCEPTED
            reverse.save(update_fields=["status"])
            return reverse
        raise ValueError("You're already friends.")
    existing = Friendship.objects.filter(from_user=from_user, to_user=to_user).first()
    if existing is not None:
        if existing.status == Friendship.ACCEPTED:
            raise ValueError("You're already friends.")
        raise ValueError("Request already sent.")
    return Friendship.objects.create(from_user=from_user, to_user=to_user)
