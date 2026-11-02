from fastapi import FastAPI

app = FastAPI(
    title="LawPilot AI",
    description="Multi-Agent AI Legal Support System",
    version="1.0.0"
)

@app.get("/")
def root():
    return {"message": "LawPilot AI Backend is running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}