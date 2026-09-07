# MIT-12 — Friends

Branch: `mit-12-friends`, based on `premium`. PR targets `premium`. Same plan is committed at `plans/mit-12.md` on the branch.

## Summary

Premium users can look up another user by exact username, send a friend request, accept or decline incoming requests, and remove friends. This is the substrate for the friends-only leaderboard filter in MIT-14, so expose one reusable query helper.

**Prior art:** the stale branch `mit-12` has a `Friendship` model and friend views/templates built against a pre-premium base that also bundled MIT-8/9 work. Read `git show mit-12:birdle/models.py` and the `friends*` templates for reference, but rebuild on `premium` (which already has allauth, profile, and Membership). Do not merge that branch.

## Data model

`Friendship`: `from_user`, `to_user` (FK user, related names `friend_requests_sent` / `friend_requests_received`), `status` in {pending, accepted}, `created_at`. `unique_together (from_user, to_user)`; a `CheckConstraint` that `from_user != to_user`. Migration `0015_friendship`. Admin registration.

Helper in `birdle/friends.py`: `friend_ids(user) -> set[int]` (accepted in either direction), `pending_incoming(user)`, `pending_outgoing(user)`, `send_request(from_user, to_user)` (raises `ValueError` if self, already friends, or a request exists in either direction; if the reverse request is pending, accept it instead).

## Views and URLs (all `premium_required`, under `accounts/friends/`)

* `friends` (GET) — list accepted friends, incoming requests with Accept/Decline, outgoing pending, and a username search form.
* `friend_request` (POST username) — exact, case-insensitive match; show "user not found" without leaking anything else. Anonymous auto-generated numeric usernames (see `daily_bird`'s `get_or_create`) can't be added: require the target to have an email or a non-numeric username.
* `friend_accept`, `friend_decline`, `friend_remove` (POST, pk) — only the involved user may act.

Nav: "Friends" link next to the profile link for premium users, with a badge for incoming request count (one cached count query, or compute in a context processor only when authenticated).

## Templates

`friends.html` extending `account/base_card.html` style; plain Bootstrap list groups and forms. Django messages for outcomes.

## Tests

`FriendTests`: send creates pending; duplicate/reverse/self rejected; reverse-pending auto-accepts; accept/decline/remove only by involved users (403 otherwise); `friend_ids` symmetric; anonymous → login, non-premium → `premium` redirect; unknown username message.

## Verification

`ruff check`, `ruff format --check`, `ty check`, `python manage.py test`, `python manage.py makemigrations --check`.

## Notes

* Other in-flight branches also add `0015_*` migrations off `0014_membership`; name yours `0015_friendship`. Renumbering at merge.
* MIT-14 (leaderboards) is being built in parallel and will call `friend_ids(user)` in a follow-up once this merges. Keep that function signature.
