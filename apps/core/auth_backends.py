"""
Staff sign-in by email address or username.

The panel asks for a single identity field. Django's default ``ModelBackend``
matches the username only, so an account created with its email address (for
example ``bm.kingchef@pasonsgrp.com``) could not sign in unless the whole
address was typed into the username box. This backend lets a person type
either one, and leaves every existing username login working unchanged.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate by email address (case-insensitive) or by username.

    Listed before ``ModelBackend`` in ``AUTHENTICATION_BACKENDS``. It returns
    ``None`` when it cannot match, so Django simply moves on to the next
    backend and the default username behaviour is preserved.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        user = self._find_user(username)
        if user is None:
            # Run the hasher once so a missing account costs the same time as a
            # wrong password. Without this, response time leaks which accounts
            # exist (the same mitigation Django applies in ModelBackend).
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _find_user(identity):
        """Resolve one identity string to a user, or None.

        Tried in order: an exact username match (case-insensitive), then an
        email match (case-insensitive). If two accounts share an email the
        lookup refuses rather than guessing, since a duplicate address would
        otherwise make sign-in ambiguous.
        """
        identity = (identity or "").strip()
        if not identity:
            return None

        field = UserModel.USERNAME_FIELD
        try:
            return UserModel.objects.get(**{f"{field}__iexact": identity})
        except UserModel.DoesNotExist:
            pass
        except UserModel.MultipleObjectsReturned:
            return None

        matches = list(UserModel.objects.filter(email__iexact=identity)[:2])
        return matches[0] if len(matches) == 1 else None
