# Data Model

Every project table in the database today, read from the Django models. `billing/` has no models yet.
A picture of the same model is in [`docs/diagrams/data-model.drawio.png`](docs/diagrams/data-model.drawio.png).

```mermaid
erDiagram
    %% core
    User |o--o{ ActivityLog : "performs"
    Patient |o--o{ ActivityLog : "about"

    %% lab
    User ||--o{ TestOrder : "enters"
    Patient ||--o{ TestOrder : "has"
    TestOrder }o--|{ TestType : "requests"
    TestOrder ||--o| Sample : "tube"
    User |o--o{ Sample : "collected_by"
    User |o--o{ Sample : "printed_by"
    TestOrder ||--o| BMPResult : "result"
    TestOrder ||--o| CBCResult : "result"
    TestOrder ||--o| LipidResult : "result"
    User ||--o{ BMPResult : "performed_by"
    User ||--o{ CBCResult : "performed_by"
    User ||--o{ LipidResult : "performed_by"

    %% inventory
    TestType ||--o{ TestSupply : "uses"
    SupplyItem ||--o{ TestSupply : "used in"
    SupplyItem ||--o{ StockLot : "has lots"
    User ||--o{ StockLot : "received_by"

    User {
        int id PK
        string username UK
        string password "hashed"
        string first_name
        string last_name
        string email
        string role "lab_manager, specimen_collector, technician, pathologist, cashier, patient, healthcare_provider"
        bool must_change_password "true until first password change"
        bool is_staff "can open /admin/"
        bool is_superuser
        bool is_active
        datetime last_login "optional"
        datetime date_joined
    }

    ActivityLog {
        int id PK
        int user_id FK "optional, empty for system events"
        int patient_id FK "optional"
        string action "e.g. order_created, sample_collected, test_blocked"
        string details "optional"
        datetime timestamp
    }

    LabInfo {
        int id PK "always 1"
        string name
        string address
        string phone
        string hours
    }

    Patient {
        int id PK
        string first_name
        string last_name
        date date_of_birth
        string gender "male, female, other, unknown"
        string address
        string phone
        string email "optional"
        string insurance_provider
        string insurance_policy_number
        bool is_active "false once removed (soft delete)"
    }

    TestType {
        int id PK
        string code UK "BMP, CBC, LIPID"
        string name
    }

    TestOrder {
        int id PK "Report ID"
        int patient_id FK
        string source "walk_in or phone_in"
        string physician_name
        string physician_license_id "trimmed, uppercased"
        string physician_phone "optional"
        string insurance_provider "copied from patient at order time"
        string insurance_policy_number
        int entered_by_id FK
        datetime created_at
        string status "pending or completed"
    }

    Sample {
        int id PK
        int order_id FK, UK "one tube per order"
        string barcode UK "the order id, set once"
        string sample_type "blood, urine, tissue"
        int collected_by_id FK "optional"
        datetime collected_at "empty until collected"
        int printed_by_id FK "optional"
        datetime printed_at "first print only"
    }

    BMPResult {
        int id PK
        int order_id FK, UK
        int performed_by_id FK
        datetime measured_at
        datetime received_at
        decimal glucose
        decimal sodium
        decimal potassium
    }

    CBCResult {
        int id PK
        int order_id FK, UK
        int performed_by_id FK
        datetime measured_at
        datetime received_at
        decimal wbc
        decimal hemoglobin
        decimal platelets
    }

    LipidResult {
        int id PK
        int order_id FK, UK
        int performed_by_id FK
        datetime measured_at
        datetime received_at
        decimal total_cholesterol
        decimal hdl
        decimal ldl
        decimal triglycerides
    }

    SupplyItem {
        int id PK
        string name "unique among active items, ignoring case"
        string unit "e.g. tubes, tests"
        bool is_active "false once removed (soft delete)"
    }

    StockLot {
        int id PK
        int item_id FK
        string lot_number
        int quantity "never below 0"
        date expiry_date
        int received_by_id FK
        datetime received_at
    }

    TestSupply {
        int id PK
        int test_type_id FK "unique with item_id"
        int item_id FK
        int quantity "units per run, at least 1"
    }
```

## Notes

- **Apps:** `User`, `ActivityLog` and `LabInfo` are in `core`. `Patient`, `TestType`, `TestOrder`, `Sample` and the three result models are in `lab`. `SupplyItem`, `StockLot` and `TestSupply` are in `inventory`.
- **Django's own tables** are left out: `Group`, `Permission`, `ContentType`, `LogEntry` (admin log), `Session` and `django_migrations`. The app controls access with `User.role` (`core/decorators.py`), not groups or permissions.
- **No link between `User` and `Patient`.** `User.role = patient` is for a future patient login (SXFT-29). Patient records created by staff are not accounts.
- **Result models** share their fields through the abstract `PanelResult` base, which has no table of its own. Each order has at most one result per panel.
- **`TestOrder.tests`** is many-to-many, stored in the hidden join table `lab_testorder_tests`. `TestType` and `TestSupply` rows are seeded by migrations.
- **`LabInfo`** always saves as row 1, so there is only ever one.
- **Deletes:** links to `Patient`, `User`, `TestOrder` (from results) and `SupplyItem` are protected, so those rows can't be hard-deleted while something points at them. Patients and supply items are soft-deleted (`is_active`) instead. A `Sample` is deleted with its order, and `TestSupply` rows go with their test type. `ActivityLog` and `Sample` keep their row and empty the user or patient link if that row is removed.
