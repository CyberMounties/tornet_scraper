# Tornet Scraper

The **Tornet Scraper** is an advanced web scraping tool designed to teach students the fundamentals of cyber threat intelligence (CTI) and open-source intelligence (OSINT). It is a key component of the **"Cyber Threat Intelligence: From Forums to Frontlines"** course offered by [Cyber Mounties Academy](https://academy.cyberm.ca).


> **Note**: We strongly recommend running `tornet_scraper` locally rather than in Docker. The proxy generator relies on Docker to create new machines that serve as Tor exit nodes, which may not function correctly when the application itself is containerized.


## Running Locally

To run the Tornet Scraper locally, follow these steps:

1. Clone the repository:
   ```bash
   git clone https://github.com/CyberMounties/tornet_scraper.git
   cd tornet_scraper
   ```

2. Install the required dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```

3. Run the FastAPI application using Uvicorn:
   ```bash
   sudo /home/hamy/tornet_scraper/venv/bin/python3 -m uvicorn app.main:app --reload
   ```

   **Note**: The `sudo` command is required on some systems (e.g., Ubuntu) due to permissions for the virtual environment or port access. Ensure your virtual environment path matches your system setup.

## Running with Docker

To run the Tornet Scraper using Docker, you need to have Docker and Docker Compose installed. Then, execute the following commands from the root directory of the project:

1. Build the Docker image:
   ```bash
   sudo docker-compose build
   ```

2. Start the container in detached mode:
   ```bash
   sudo docker-compose up -d
   ```

   **Note**: The `sudo` command may be required on systems like Ubuntu for Docker operations. The application will be accessible at `http://localhost:8000`.

