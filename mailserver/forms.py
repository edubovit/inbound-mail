from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Account, username_validator


class LoginForm(forms.Form):
    username = forms.CharField(max_length=320, label="Username or email", widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}))
    password = forms.CharField(max_length=1024, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class AccountForm(forms.Form):
    username = forms.CharField(max_length=64, validators=[username_validator])
    role = forms.ChoiceField(choices=Account._meta.get_field("role").choices)
    quota_mib = forms.IntegerField(min_value=1, max_value=1048576, label="Mailbox quota (MiB)")
    password = forms.CharField(min_length=12, max_length=1024, label="Temporary password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_username(self):
        username = self.cleaned_data["username"]
        if ".." in username:
            raise ValidationError("Consecutive dots are not allowed.")
        if Account.objects.filter(username=username).exists():
            raise ValidationError("This address already exists.")
        return username

    def clean(self):
        data = super().clean()
        if data.get("password"):
            validate_password(data["password"], Account(username=data.get("username", "")))
        return data


class EditAccountForm(forms.Form):
    role = forms.ChoiceField(choices=Account._meta.get_field("role").choices)
    quota_mib = forms.IntegerField(min_value=1, max_value=1048576, label="Mailbox quota (MiB)")


class ResetForm(forms.Form):
    password = forms.CharField(min_length=12, max_length=1024, label="Temporary password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))


class ConfirmForm(forms.Form):
    confirm = forms.BooleanField(label="I understand and confirm")
