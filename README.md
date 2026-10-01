# Smart Blood & Emergency Donor Network

Web platform that connects people who urgently need blood with compatible donors:
request -> verification -> smart donor matching -> notifications -> donor response -> donation confirmation -> analytics.

**Live app:** PASTE-YOUR-RENDER-LINK-HERE

## Demo logins
| Role | Email | Password |
|---|---|---|
| Admin | admin@demo.com | admin123 |
| Coordinator | coord@demo.com | coord123 |
| Requester | req@demo.com | req123 |
| Donor | donor1@demo.com | donor123 |

## Structure
- `app.py` - Flask backend: API, SQLite database, donor matching and escalation, notifications, statistics
- `static/index.html` - frontend for all four roles
- `requirements.txt` - Python dependencies

## Folder Sequence In System 
blood-network/
  , app.py
  requirements.txt, 
  README.md, 
  static/index.html, 
  database/schema.sql, 
  docs/Project_Explanation_Document.docx

## Run locally
```
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000
