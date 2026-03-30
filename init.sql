-- Create database
CREATE DATABASE flaskdb;

-- Create user
CREATE USER flaskuser WITH PASSWORD 'MyStrongPassword123';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE flaskdb TO flaskuser;
