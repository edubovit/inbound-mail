from django.urls import path

from . import views

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("inbox/updates/", views.inbox_updates, name="inbox_updates"),
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("password/", views.password, name="password"),
    path("messages/<int:pk>/", views.message, name="message"),
    path("messages/<int:pk>/html/", views.message_html, name="message_html"),
    path("messages/<int:pk>/attachments/<int:index>/", views.attachment, name="attachment"),
    path("messages/<int:pk>/read/", views.read_state, name="read_state"),
    path("messages/<int:pk>/delete/", views.delete_message, name="delete_message"),
    path("admin/", views.accounts, name="accounts"),
    path("admin/create/", views.create_account, name="create_account"),
    path("admin/accounts/<int:pk>/", views.edit_account, name="edit_account"),
    path("admin/accounts/<int:pk>/reset/", views.reset_password, name="reset_password"),
    path("admin/accounts/<int:pk>/delete/", views.delete_account, name="delete_account"),
    path("admin/export/", views.export, name="export"),
    path("assets/style.css", views.stylesheet),
    path("assets/message.css", views.message_stylesheet),
    path("assets/inbox.js", views.inbox_script),
    path("assets/select.js", views.select_script),
    path("favicon.ico", views.favicon),
    path("health/", views.health),
]
