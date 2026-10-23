from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

USERNAME_PATTERN = r"\A[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?\Z"
username_validator = RegexValidator(USERNAME_PATTERN, "Use 1–64 lowercase letters, numbers, dots, hyphens or underscores; start and end with a letter or number.")


class AccountManager(BaseUserManager):
    def create_user(self, username, password=None, **fields):
        account = self.model(username=username.lower(), **fields)
        account.set_password(password)
        account.full_clean()
        account.save(using=self._db)
        return account

    def create_superuser(self, username, password=None, **fields):
        return self.create_user(username, password, role="ADMIN", **fields)


class Account(AbstractBaseUser):
    username = models.CharField(max_length=64, unique=True, validators=[username_validator])
    role = models.CharField(max_length=5, choices=[("USER", "USER"), ("ADMIN", "ADMIN")], default="USER")
    quota_bytes = models.PositiveBigIntegerField(default=settings.DEFAULT_QUOTA_BYTES)
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = AccountManager()
    USERNAME_FIELD = "username"

    def clean(self):
        super().clean()
        if ".." in self.username:
            raise ValidationError({"username": "Consecutive dots are not allowed."})

    @property
    def address(self):
        return f"{self.username}@{settings.MAIL_DOMAIN}"

    @property
    def is_staff(self):
        return self.role == "ADMIN"


class Message(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="mail")
    raw = models.BinaryField()
    size = models.PositiveIntegerField()
    sender = models.CharField(max_length=512, blank=True)
    subject = models.CharField(max_length=512, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["account", "-id"])]


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
