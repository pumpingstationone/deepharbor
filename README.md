# Deep Harbor CRM
## Purpose
The Deep Harbor CRM was written to support membership at [Pumping Station: One](https://pumpingstationone.org). It's meant to be performant and flexable, subscribing to the concept of _"You don't know what you don't know."_ What this means is that the system is designed to be easy to extend and modify to fit new situations with minimal changes.
## General Design
To facilitate easy changes, Deep Harbor is built around the concept of _web services_. Services are grouped around areas of responsibility; specific functionality is encapsulated within a set of service calls that provide only what is necessary to perform tasks related to what the service is responsible for. For example, there is a "worker" service called `DH2AD` (all Deep Harbor comppnents are prefixed with `DH` or `dh_`) that exposes a set of web service API that allow Deep Harbor data to be sent to Active Directory.
## Components
Deep Harbor is comprised of the following components:
* DHAdminPortal
This is a front-end website that is used by administrators, authorizers (folks who are tasked with teaching other members how to use certain equipment), and any other person who has been granted `MEMBER_CHANGE_ACCESS`.
* DHMemberPortal
This is the front end that the member or prospective member interacts with. It is here that they create an account, set up payments, configure access (i.e. RFID) tags, and other individual-specific tasks that are not related to administration (for example, individual members cannot authorize themselves on equipment).
* DHDispatcher
This program does not expose web services but instead listens for notifications from the Postgres database and invokes the appropriate service based on the changed data. It does not care what is the origin of the changed data but merely that some other system needs to be informed that some change has, in fact, happened.

The following components are "business services" insofar as they are responsible for performing whatever tasks are necessary based on the change order from the DHDispatcher.

* DHAccess
Handles all access-specific tasks. At Pumping Station One this is RFID-based and is used to control door access. Note that DHAccess itself does not have any knowledge of RFID systems but rather gathers all the relevant information to complete the task (in this case, retrieving RFID tags from the database) and passing that to `DH2RFID` (described below) to perform the actual work.
* DHAuthorizations
Pumping Station One's equipment policy is that a member must be authorized before they are allowed to use tools, especially complex and potentially dangerous ones. Authorization provides two purposes: to ensure the member has sufficient knowledge to use a particular tool, and in certain cases, allow access to the tool's computer (via Active Directory) so they can actually use it.

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;The DHAuthorizations service performs whatever tasks are necessary to configure authorizations for a particular member in whatever system is necessary to be configured to allow access to the tool (for example, invoking `DH2AD` to put the member in a certain OU so they can log into the computer that controls the tool).
* DHIdentity
Anything that might relate to a change of name, nickname, or other identifying component is handled by DHIdentity.
* DHStatus
Change of status (membership level, etc.) is handled bny this service.

The following components are "worker services" in that they perform whatever low-level functionality is necessary to accomplish the task. Worker services do not have any business logic nor do they communicate with the Deep Harbor database; all relevant components are sent to the worker service and the worker service's only task is to interface to whatever system they work with.

* DH2AD
This service manipulates a member's information within Active Directory.
* DH2RFID
This service adds and removes RFID tags from the controller database to either allow or deny access to the premises.

## Directory Structure
* `pg/`: Contains PostgreSQL database initialization scripts and configuration files.
* `DHAdminPortal/`: Source code for the administrative web portal.
* `DHMemberPortal/`: Source code for the member-facing web portal.
* `DHDispatcher/`: Source code for the dispatcher service that listens for database notifications.
* `services/DHAccess/`: Source code for the access management service.
* `services/DHAuthorizations/`: Source code for the authorizations management service.
* `services/DHIdentity/`: Source code for the identity management service.
* `services/DHStatus/`: Source code for the status management service.
* `workers/DH2AD/`: Source code for the Active Directory integration service.
* `workers/DH2RFID/`: Source code for the RFID integration service.
* `pg/`: Contains all the PostgreSQL-based files including SQL schema definitions and database-related scripts.
* `tools/`: Scripts and other files used for development and maintenance tasks (e.g., database migrations, backups).
### Additional Files
These files are located in the root directory of the Deep Harbor CRM project:
* `docker-compose.yaml`: Docker Compose configuration file to set up the entire Deep Harbor CRM environment
* `start_dh.sh`: Script to start all Deep Harbor components.
* `stop_dh.sh`: Script to stop all Deep Harbor components.
* `reset_for_restart.sh`: Script to reset the Deep Harbor environment for a fresh start.
* `README.md`: This file, providing an overview and instructions for the Deep Harbor CRM project.
* `nginx.conf`: Nginx configuration file for routing requests to the appropriate Deep Harbor components.


## Getting Started
To get started with Deep Harbor CRM, follow these steps:
0. **Install Docker and Docker Compose**:
   Ensure that Docker and Docker Compose are installed on your machine. You can download them from the [Docker website](https://www.docker.com/get-started).
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/pumpingstationone/deepharbor.git
    cd deepharbor
    ```
2. **`start_dh.sh` Script**:
   Use the provided `start_dh.sh` script to set up and start all necessary components. This script will handle starting the database, web portals, dispatcher, and services.
   ```bash
   ./start_dh.sh
   ```
   To stop all components, use:
   ```bash
   ./stop_dh.sh
    ```
   If you need to reset everything (including the database), use:
   ```bash
   ./reset_for_restart.sh
   ```
