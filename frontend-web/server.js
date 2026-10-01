// Minimal Node/Express server that serves the static frontend.
// The browser calls the FastAPI backend (http://localhost:8000) directly;
// CORS is enabled on the backend so that works.
import express from "express";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.static(join(__dirname, "public")));

app.listen(PORT, () => {
  console.log(`Frontend running at http://localhost:${PORT}`);
  console.log("Make sure the backend is running: uvicorn app:app --port 8000");
});
