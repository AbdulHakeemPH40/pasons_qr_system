"""
Sign-in identity for the staff panel.

The superuser may type a username or an email address. Brand users and
branch users sign in with a username only. An email address stored on
those accounts is not a login, so typing it must not open the panel.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """Username for every account. Email only for the superuser.

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

        Username matches every account, case-insensitive. An email match is
        accepted only when the single matching account is a superuser. Brand
        and branch users must use their username, even if the typed string
        equals an email stored on their account.
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

        matches = list(
            UserModel.objects.filter(email__iexact=identity, is_superuser=True)[:2]
        )
        return matches[0] if len(matches) == 1 else None
