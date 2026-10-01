# Start from an official slim Python image matching your project's version.
FROM python:3.13-slim

# PYTHONDONTWRITEBYTECODE: don't create .pyc files (not needed in a container).
# PYTHONUNBUFFERED: stream logs straight to stdout so you see them live
# (remember Lesson 2 - this is what makes your structured logs show up).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# All following commands run inside this directory in the container.
WORKDIR /app

# Copy ONLY requirements first, then install. Docker caches this layer, so if
# your code changes but deps don't, rebuilds skip re-installing (much faster).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of your application code.
COPY . .

# Document that the app listens on 8000 (doesn't publish it - compose does that).
EXPOSE 8000

# The command that runs when the container starts.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]