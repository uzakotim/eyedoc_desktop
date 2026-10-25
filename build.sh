source .venv/bin/activate

# Run frontend build
cd frontend
npm run build

# Run backend build
cd ..
# If windows
if [ $(uname) == "Windows_NT" ]; then
    pyinstaller --noconsole --onefile --add-data "frontend/dist;frontend/dist" backend/app.py
else
    pyinstaller --noconsole --onefile --add-data "frontend/dist:frontend/dist" backend/app.py
fi