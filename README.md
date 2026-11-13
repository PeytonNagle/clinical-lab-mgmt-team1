# Clinical Laboratory Management System (CLMS)

SFWE 403 semester project, Group 1. Django + PostgreSQL + Bootstrap.

## Run locally

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed      # fake users, patients, orders and stock; safe to re-run
python manage.py runserver # http://127.0.0.1:8000/
```

### Test logins

Created by `seed`. **Fake and for local testing only. Never run `seed` on a shared or deployed server.**
Every account uses the password `TestPass123!`.

| Username       | Role               |
| -------------- | ------------------ |
| `manager1`     | Lab manager (can also open `/admin/`) |
| `collector1`   | Specimen collector |
| `tech1`        | Technician         |
| `pathologist1` | Pathologist        |
| `cashier1`     | Cashier            |

- To add users in `/admin/`, first make `manager1` a superuser (one time; survives re-seeding):
  `python manage.py shell -c "from core.models import User; User.objects.filter(username='manager1').update(is_superuser=True)"`
- Seeded users skip the first-login password change. To test it, add a new user in `/admin/`.
- No patient or provider users are seeded. Add one in `/admin/` if you need one.

### Set up a new lab

Only lab managers can create accounts, so whoever installs the system creates the first one:
`python manage.py create_lab_manager <username> [--email EMAIL]`. It prints a temporary password, which the manager must change on first login.

### Account lockout

Five wrong passwords in a row lock that username (django-axes). A correct password before the fifth resets the count.
The lock never expires on its own. A lab manager unlocks it on **Locked accounts** (`/accounts/locked/`, in the navbar). The username is locked, not the computer, so others can still sign in from the same machine.

If the only lab manager is locked out, unlock them from the server:

```sh
python manage.py axes_reset_username <username>
```

When an account locks, every active lab manager with an email address gets one email, and the lockout goes in the activity log.

### Email

With no email settings, emails print in the `runserver` terminal. No account is needed.

To see them in an inbox, each person makes their own free [Mailtrap](https://mailtrap.io) sandbox (don't share credentials). It never delivers to real addresses.

1. In Mailtrap, open your sandbox's SMTP credentials and copy the username and password.
2. Add them to `.env` (see `.env.example`):

   ```sh
   EMAIL_HOST=sandbox.smtp.mailtrap.io
   EMAIL_PORT=2525
   EMAIL_HOST_USER=<username>
   EMAIL_HOST_PASSWORD=<password>
   ```

3. Check it: `python manage.py sendtestemail manager1@example.com` should land in your sandbox. Seeded managers have no email, so set one in `/admin/` to receive lockout emails.
4. Restart `runserver`. Lockout emails now show up in your sandbox.

`CERTIFICATE_VERIFY_FAILED`? Python from python.org needs its certificates installed once: `open "/Applications/Python 3.13/Install Certificates.command"`.

Sending real email later only means pointing these settings at a real mail server. If sending fails, sign-in still works and the failure goes in the activity log.

## Folders

| Folder         | What goes in                                                                        | When                           |
| -------------- | ----------------------------------------------------------------------------------- | ------------------------------ |
| `core/`        | User model with roles, login and passwords, activity log, `role_required`, reports  | MVP 1 (login), MVP 2 (reports) |
| `lab/`         | Patients, physicians, test orders, samples, barcodes, results, `importer.py`        | MVP 1                          |
| `inventory/`   | Supply items, stock lots with expiry, what each test uses, `stock.py`               | MVP 2                          |
| `billing/`     | Purchases, payment types, receipts                                                  | MVP 2                          |
| `templates/`   | HTML pages: `base.html` + one subfolder per app                                     | Every story                    |
| `config/`      | `settings.py` and `urls.py` (small edits only)                                      | When adding an app or URL      |
| `sample_data/` | Fake machine result `.txt` files                                                    | MVP 1                          |
| `static/`      | Custom CSS or images (only if needed)                                               | Anytime                        |

## Inside each app

| File        | Purpose                     |
| ----------- | --------------------------- |
| `models.py` | Database tables             |
| `views.py`  | Page logic                  |
| `urls.py`   | Page addresses (create it)  |
| `forms.py`  | Forms (create it)           |
| `admin.py`  | Admin panel setup           |
| `tests.py`  | Tests                       |

## Pages

Every page requires login except the login page.

| URL                | Page                                                                 |
| ------------------ | -------------------------------------------------------------------- |
| `/`                | Sends you to your role's home page (logged out: to login)            |
| `/home/<role>/`    | Placeholder home page per staff role, e.g. `/home/technician/`       |
| `/accounts/login/` | Login, with Staff / Patient / Healthcare provider tabs (Staff only for now) |
| `/accounts/logout/` | Logout (POST only, via the navbar button)                           |
| `/accounts/password/set/` | First login: replace the temporary password (forced until done) |
| `/accounts/password/change/` | Change password, from the navbar                             |
| `/patients/`       | Patient list with search; any staff role. Also linked in the navbar  |
| `/patients/new/`   | Create a patient account (any staff role)                            |
| `/patients/<id>/edit/` | Update a patient account (any staff role)                        |
| `/patients/<id>/remove/` | Remove (deactivate) a patient: lab manager, specimen collector, or cashier |
| `/orders/`         | Order list, newest first, 25 per page; any staff role. Also linked in the navbar |
| `/orders/new/`     | Place a test order, with insurance filled in from the patient (any staff role) |
| `/orders/<id>/`    | Order detail: patient, physician, insurance and tests                |
| `/staff/register/` | Create a staff account (lab manager only)                            |
| `/accounts/locked/` | Locked accounts, with an Unlock button for each (lab manager only). Also linked in the navbar |
| `/results/upload/` | Upload a machine result `.txt` file (technician). Format and Test IDs: top of `lab/importer.py` |
| `/inventory/`      | Supply list with stock left and next expiry (lab manager). Also linked in the navbar |
| `/inventory/new/`  | Add a supply item (lab manager)                                      |
| `/inventory/<id>/` | One item's lots, soonest expiry first, and which tests use it. Edit, remove and receive from here |
| `/inventory/<id>/receive/` | Receive a delivery: lot number, quantity and expiry (lab manager) |
| `/inventory/lots/<id>/edit/` | Correct a lot after a stock count (lab manager)            |
| `/admin/`          | Django admin. Opens for users with `is_staff`; editing needs a superuser |

## Rules

- Branch name: `SXFT-xx-short-name`. Never push to `main`.
- Changed a model? Run `python manage.py makemigrations` and commit the migration.

## UI conventions

- Feature not built yet? Show it greyed out with a hint: `{% include "partials/not_implemented.html" with label="Export" %}`.
