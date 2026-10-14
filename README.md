# Clinical Laboratory Management System (CLMS)

SFWE 403 semester project, Group 1. Django + PostgreSQL + Bootstrap.

## Folders

| Folder         | What goes in                                                                        | When                           |
| -------------- | ----------------------------------------------------------------------------------- | ------------------------------ |
| `core/`        | User model with roles, login and passwords, activity log, `role_required`, reports  | MVP 1 (login), MVP 2 (reports) |
| `lab/`         | Patients, physicians, test orders, samples, barcodes, results, `importer.py`        | MVP 1                          |
| `inventory/`   | Reagents and kits, stock, expiry, reorders                                          | MVP 2                          |
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
| `/admin/`          | Django admin, for users with `is_staff`                              |

## Rules

- Branch name: `SXFT-13-short-name`. Never push to `main`.
- Open a PR, get 1 approval, then merge.
- Changed a model? Run `python manage.py makemigrations` and commit the migration.

## UI conventions

- Feature not built yet? Show it greyed out with a hint: `{% include "partials/not_implemented.html" with label="Export" %}`.
