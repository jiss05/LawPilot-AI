# LawPilot AI - Email OTP setup

## What was added

- Registration creates a pending account (`email_verified=false`, `is_active=false`).
- A random six-digit OTP is generated and emailed to the registered address.
- Only an Argon2 hash of the OTP is stored in PostgreSQL.
- OTP expires after five minutes and permits at most five verification attempts.
- Resending is limited to once every 60 seconds.
- Successful verification sets `email_verified=true` and `is_active=true`.
- Login and protected API requests reject unverified accounts.

## SMTP configuration

Copy `.env.example` to `.env` if you do not already have a `.env` file. Keep the existing working `DATABASE_URL` and `JWT_SECRET_KEY` values in your private `.env`.

For Gmail:
1. Enable 2-Step Verification on the Google account.
2. Create a Google App Password.
3. Set `EMAIL_USERNAME` to the sending Gmail address.
4. Set `EMAIL_PASSWORD` to the App Password (not the normal Gmail password).
5. Optionally set `EMAIL_FROM` to the same sending address.

Never commit `.env` or share its contents.

## New API flow

1. `POST /api/v1/auth/register`
   ```json
   {
     "display_name": "Example User",
     "email": "user@example.com",
     "password": "StrongPassword123"
   }
   ```
   The API sends an OTP and returns a pending-verification message.

2. `POST /api/v1/auth/verify-email`
   ```json
   {
     "email": "user@example.com",
     "otp": "123456"
   }
   ```

3. `POST /api/v1/auth/resend-otp`
   ```json
   {
     "email": "user@example.com"
   }
   ```

4. After verification, use the existing `POST /api/v1/auth/login` endpoint.

## Database migration - do not run until the team approves

A new Alembic migration adds `users.email_verified` and creates `email_otps`.

After the team confirms that the shared database may be changed, run from the backend directory:

```powershell
alembic upgrade head
```

This command changes the database schema. Do not run it against the shared database before receiving the team's approval.

The existing CLIENT role seed is still required for public registration. This OTP change does not seed or modify the four global roles.
