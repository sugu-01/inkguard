
# InkGuard API Documentation

## API Routes

| Route | Who | Purpose |
|---|---|---|
| GET /health | Anyone | Check if the server is running |
| POST /check | Anyone | Check text for findings |
| GET /rules | Brand manager | View rules |
| POST /rules/compile | Brand manager | Compile rules |
| POST /rules/{id}/approve | Brand manager | Approve a rule |
| GET /facts | Brand manager | View facts |
| POST /facts | Brand manager | Add facts |
| POST /submissions | Creator | Submit content |
| GET /submissions | Creator | List submissions |
| POST /submissions/{id}/decision | Reviewer | Submit a review decision |
| GET /audit | Anyone | View audit trail |
| GET /insights | Anyone | View chart and insight data |

## Request and Response Models

- POST /check accepts a CheckRequest containing text.
- POST /check returns a CheckResponse containing findings and AI availability.
- POST /submissions/{id}/decision accepts a Decision object.

## Role Header

The demo uses the X-Role header to identify the user's role.

Example:

X-Role: Brand manager

This is a demo shortcut, not secure authentication.
The server must enforce role permissions in the real application.
