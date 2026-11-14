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
| `/lab/collect/` | Collect samples (collector, lab manager). Also in the navbar |
| `/samples/<id>/label/` | Tube label with barcode (collector prints once; lab manager reprints) |
| `/lab/collect/samples/<id>/supplies/` | Run test supply check (collector runs, lab manager views) |
| `/staff/register/` | Create a staff account (lab manager only)                            |
| `/results/upload/` | Upload a machine result `.txt` file (technician). Format and Test IDs: top of `lab/importer.py` |
| `/inventory/`      | Supply list with stock left and next expiry (lab manager). Also linked in the navbar |
| `/inventory/new/`  | Add a supply item (lab manager)                                      |
| `/inventory/<id>/` | One item's lots, soonest expiry first, and which tests use it. Edit, remove and receive from here |
| `/inventory/<id>/receive/` | Receive a delivery: lot number, quantity and expiry (lab manager) |
| `/inventory/lots/<id>/edit/` | Correct a lot after a stock count (lab manager)            |
| `/admin/`          | Django admin. Opens for users with `is_staff`; editing needs a superuser |

## Barcodes and labels

- A collector can print a sample's label once. Later visits show "already printed".
- Only the lab manager can reprint, and must give a reason.
- Prints and reprints (with reason) are in the activity log.

## Inventory and supply checks

- `seed` adds fake lots. The hematology reagent pack has no stock, so **Run test** on a CBC sample reports it out of stock. One BMP cartridge lot is expired.
- Result uploads take stock soonest-expiring first. If stock is short, the result is still saved and a warning shows on the upload page only (not logged).
- **Run test** only warns; it doesn't block anything later. The block is logged only when the collector clicks **Run test** on the check page.
- A superuser sets test supplies in `/admin/` under **Test supplies**.

## Rules

- Branch name: `SXFT-xx-short-name`. Never push to `main`.
- Changed a model? Run `python manage.py makemigrations` and commit the migration.

## UI conventions

- Feature not built yet? Show it greyed out with a hint: `{% include "partials/not_implemented.html" with label="Export" %}`.
