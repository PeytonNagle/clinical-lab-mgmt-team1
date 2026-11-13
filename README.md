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
| `/lab/collect/`    | Collect samples: orders waiting, and today's collections (specimen collector, lab manager). Also linked in the navbar |
| `/samples/<id>/label/` | Tube label with barcode. Collector prints it once; lab manager can view and reprint |
| `/lab/collect/samples/<id>/supplies/` | Run test: checks supplies for a collected sample (collector runs it, lab manager views) |
| `/staff/register/` | Create a staff account (lab manager only)                            |
| `/results/upload/` | Upload a machine result `.txt` file (technician). Format and Test IDs: top of `lab/importer.py` |
| `/inventory/`      | Supply list with stock left and next expiry (lab manager). Also linked in the navbar |
| `/inventory/new/`  | Add a supply item (lab manager)                                      |
| `/inventory/<id>/` | One item's lots, soonest expiry first, and which tests use it. Edit, remove and receive from here |
| `/inventory/<id>/receive/` | Receive a delivery: lot number, quantity and expiry (lab manager) |
| `/inventory/lots/<id>/edit/` | Correct a lot after a stock count (lab manager)            |
| `/admin/`          | Django admin. Opens for users with `is_staff`; editing needs a superuser |

## Barcodes and labels

Each sample's barcode is its order's ID, so machine result files that use the order ID match it.
`lab/barcodes.py` draws it as a Code 128 barcode with the `python-barcode` package. It is already in `requirements.txt`, so `pip install -r requirements.txt` is all you need. There are no image files and no printer setup.

**Print a label:**

1. Log in as `collector1`, open **Collect samples** and collect an order's sample.
2. On the label page, click **Print label**. The browser's print dialog opens and only the label prints.

**Print once:**

- A collector can print a label one time. Right after printing the label still shows so the print dialog works; on any later visit the page shows "already printed" with who printed it and when, and hides the label.
- Only the collector can make the first print. The lab manager can always see the label. To print it again, the manager gives a reason (for example "label smudged") and clicks **Reprint**. Collectors can't reprint.
- Prints and reprints (with the reason) go in the activity log. A reprint doesn't change the first print's time or user.

## Inventory and supply checks

| Term        | Meaning                                                                      |
| ----------- | ---------------------------------------------------------------------------- |
| Supply item | Something the lab keeps in stock, like a tube type or reagent, with a unit   |
| Lot         | One delivery of an item: lot number, how many are left, and an expiry date   |
| Test supply | How many units of an item one run of a test uses, e.g. a BMP uses 1 gold top tube |

Stock for an item is the sum of its lots that have some left and are not past their expiry date. Removed (inactive) supply items are left out of stock use and supply checks.

**Starting data.** `migrate` adds six supply items and what BMP, CBC and LIPID use (no stock). `seed` then adds fake lots, only if there are no lots yet: gold top tubes (one lot expires in 10 days), lavender top tubes, BMP and lipid cartridges, and pipette tips. One BMP cartridge lot is already expired. The hematology reagent pack has no lots, so it shows 0 on `/inventory/` and **Run test** on a CBC sample reports it out of stock.

**Result uploads.** For each panel it saves, `/results/upload/` takes that test's supplies from stock, soonest-expiring lot first. Expired and empty lots are skipped. A lot never goes below zero.

**When supplies run out.** The result is still saved, because the machine has already run the test. The upload page lists a **Stock warning** such as `Order 12, BMP: Pipette tips ran out, 2 tips short`. The warning is shown only on that page and is not in the activity log, so tell the lab manager right away.

**Run test (before the machine).** In the **Collected today** table on **Collect samples**, **Run test** opens a supply check for that sample (for older samples, go to `/lab/collect/samples/<id>/supplies/`). It lists anything out of stock, expired or low. When the collector clicks **Run test** on that page and something is short, the block goes in the activity log with the order, sample and tests. The check is a warning only: nothing later stops the sample from being sent or its results from being uploaded.

**Set which supplies a test uses.** There is no page for this. As a superuser (see the `manager1` step under Test logins), in `/admin/`, open **Test supplies** and add or change a row (test, item, quantity per run). An item can be added once per test. Supply items and lots are managed on the `/inventory/` pages.

## Rules

- Branch name: `SXFT-xx-short-name`. Never push to `main`.
- Changed a model? Run `python manage.py makemigrations` and commit the migration.

## UI conventions

- Feature not built yet? Show it greyed out with a hint: `{% include "partials/not_implemented.html" with label="Export" %}`.
