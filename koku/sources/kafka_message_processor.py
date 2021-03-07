#
# Copyright 2020 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
import json
import logging

from rest_framework.exceptions import ValidationError

from api.provider.models import Provider
from sources import storage
from sources.config import Config
from sources.sources_http_client import SourcesHTTPClient
from sources.sources_http_client import SourcesHTTPClientError


LOG = logging.getLogger(__name__)

KAFKA_APPLICATION_CREATE = "Application.create"
KAFKA_APPLICATION_UPDATE = "Application.update"
KAFKA_APPLICATION_DESTROY = "Application.destroy"
KAFKA_AUTHENTICATION_CREATE = "Authentication.create"
KAFKA_AUTHENTICATION_UPDATE = "Authentication.update"
KAFKA_SOURCE_UPDATE = "Source.update"
KAFKA_SOURCE_DESTROY = "Source.destroy"
KAFKA_HDR_RH_IDENTITY = "x-rh-identity"
KAFKA_HDR_EVENT_TYPE = "event_type"

SOURCES_OCP_SOURCE_NAME = "openshift"
SOURCES_AWS_SOURCE_NAME = "amazon"
SOURCES_AWS_LOCAL_SOURCE_NAME = "amazon-local"
SOURCES_AZURE_SOURCE_NAME = "azure"
SOURCES_AZURE_LOCAL_SOURCE_NAME = "azure-local"
SOURCES_GCP_SOURCE_NAME = "google"
SOURCES_GCP_LOCAL_SOURCE_NAME = "google-local"

SOURCE_PROVIDER_MAP = {
    SOURCES_OCP_SOURCE_NAME: Provider.PROVIDER_OCP,
    SOURCES_AWS_SOURCE_NAME: Provider.PROVIDER_AWS,
    SOURCES_AWS_LOCAL_SOURCE_NAME: Provider.PROVIDER_AWS_LOCAL,
    SOURCES_AZURE_SOURCE_NAME: Provider.PROVIDER_AZURE,
    SOURCES_AZURE_LOCAL_SOURCE_NAME: Provider.PROVIDER_AZURE_LOCAL,
    SOURCES_GCP_SOURCE_NAME: Provider.PROVIDER_GCP,
    SOURCES_GCP_LOCAL_SOURCE_NAME: Provider.PROVIDER_GCP_LOCAL,
}


class SourcesMessageError(ValidationError):
    """Sources Message error."""


class SourceDetails:
    def __init__(self, auth_header, source_id):
        sources_network = SourcesHTTPClient(auth_header, source_id)
        details = sources_network.get_source_details()
        self.name = details.get("name")
        self.source_type_id = int(details.get("source_type_id"))
        self.source_uuid = details.get("uid")
        self.source_type_name = sources_network.get_source_type_name(self.source_type_id)
        self.source_type = None


class KafkaMessageProcessor:
    def __init__(self, msg, event_type, cost_mgmt_id):
        try:
            self.value = json.loads(msg.value().decode("utf-8"))
            LOG.info(f"EVENT TYPE: {event_type} | MESSAGE VALUE: {str(self.value)}")
        except (AttributeError, ValueError, TypeError) as error:
            LOG.error(f"Unable to load message: {msg.value}. Error: {error}")
            raise SourcesMessageError("Unable to load message")
        self.event_type = event_type
        self.cost_mgmt_id = cost_mgmt_id
        self.offset = msg.offset()
        self.partition = msg.partition()
        self.auth_header = extract_from_header(msg.headers(), KAFKA_HDR_RH_IDENTITY)
        self.source_id = None

    def __repr__(self):
        return (
            f"Event type: {self.event_type} | Source ID: {self.source_id} |"
            f" Partition: {self.partition} | Offset: {self.offset}"
        )

    def msg_for_cost_mgmt(self):
        """Filter messages not intended for cost management."""
        if self.event_type in (KAFKA_APPLICATION_DESTROY, KAFKA_SOURCE_DESTROY):
            return True
        if self.event_type in (KAFKA_AUTHENTICATION_CREATE, KAFKA_AUTHENTICATION_UPDATE):
            sources_network = self.get_sources_client()
            return sources_network.get_application_type_is_cost_management(self.cost_mgmt_id)
        return True

    def get_sources_client(self):
        return SourcesHTTPClient(self.auth_header, self.source_id)

    def get_source_details(self):
        return SourceDetails(self.auth_header, self.source_id)

    def sources_details(self):
        """
        Get additional sources context from Sources REST API.
        Additional details retrieved from the network includes:
            - Source Name
            - Source Type
            - Source UID
        Details are stored in the Sources database table.
        """
        details = self.get_source_details()
        details.source_type = SOURCE_PROVIDER_MAP.get(details.source_type_name)
        if not details.source_type:
            LOG.warning(f"Unexpected source type ID: {details.source_type_id}")
            return
        return storage.add_provider_sources_details(details, self.source_id)

    def save_credentials(self):
        """
        Store Sources Authentication information given an Source ID.
        This method is called when a Cost Management application is
        attached to a given Source as well as when an Authentication
        is created.  We have to handle both cases since an
        Authentication.create event can occur before a Source is
        attached to the Cost Management application.
        Authentication is stored in the Sources database table.
        """
        source_type = storage.get_source_type(self.source_id)

        if not source_type:
            LOG.info(f"Source ID not found for ID: {self.source_id}")
            return

        sources_network = self.get_sources_client()

        try:
            authentication = {"credentials": sources_network.get_credentials(source_type)}
        except SourcesHTTPClientError as error:
            LOG.info(f"Authentication info not available for Source ID: {self.source_id}")
            sources_network.set_source_status(error)
        else:
            if not authentication.get("credentials"):
                return
            saved = storage.add_provider_sources_auth_info(self.source_id, authentication)
            if saved:
                LOG.info(f"Authentication attached to Source ID: {self.source_id}")
                return True

    def save_billing_source(self):
        """
        Store Sources Authentication information given an Source ID.
        This method is called when a Cost Management application is
        attached to a given Source as well as when an Authentication
        is created.  We have to handle both cases since an
        Authentication.create event can occur before a Source is
        attached to the Cost Management application.
        Authentication is stored in the Sources database table.
        """
        source_type = storage.get_source_type(self.source_id)

        if not source_type:
            LOG.info(f"Source ID not found for ID: {self.source_id}")
            return

        sources_network = self.get_sources_client()

        try:
            data_source = {"data_source": sources_network.get_data_source(source_type)}
        except SourcesHTTPClientError as error:
            LOG.info(f"Billing info not available for Source ID: {self.source_id}")
            sources_network.set_source_status(error)
        else:
            if not data_source.get("data_source"):
                return
            saved = storage.add_provider_sources_billing_info(self.source_id, data_source)
            if saved:
                LOG.info(f"Billing info attached to Source ID: {self.source_id}")
                return True


class ApplicationMsgProcessor(KafkaMessageProcessor):
    def __init__(self, msg, event_type, cost_mgmt_id):
        super().__init__(msg, event_type, cost_mgmt_id)
        self.source_id = int(self.value.get("source_id"))

    def process(self):
        if self.event_type in (KAFKA_APPLICATION_CREATE,):
            storage.create_source_event(self.source_id, self.auth_header, self.offset)

        if storage.is_known_source(self.source_id):
            if self.event_type in (KAFKA_APPLICATION_CREATE,):
                self.sources_details()
                self.save_billing_source()
                if storage.get_source_type(self.source_id) == Provider.PROVIDER_OCP:  # of course, OCP is the oddball
                    self.save_credentials()
            if self.event_type in (KAFKA_APPLICATION_UPDATE,):
                # Because azure auth is split in Sources backend, we need to check both
                # auth and billing when we recieve either auth update or app update event
                updated = any((self.save_billing_source(), self.save_credentials()))
                if updated:
                    LOG.info(f"Source ID {self.source_id} updated")
                    storage.enqueue_source_update(self.source_id)
                else:
                    LOG.info(f"Source ID {self.source_id} not updated. No changes detected.")

        if self.event_type in (KAFKA_APPLICATION_DESTROY,):
            storage.enqueue_source_delete(self.source_id, self.offset, allow_out_of_order=True)


class AuthenticationMsgProcessor(KafkaMessageProcessor):
    def __init__(self, msg, event_type, cost_mgmt_id):
        super().__init__(msg, event_type, cost_mgmt_id)
        self.source_id = int(self.value.get("source_id"))

    def process(self):
        if self.event_type in (KAFKA_AUTHENTICATION_CREATE):
            storage.create_source_event(self.source_id, self.auth_header, self.offset)

        if storage.is_known_source(self.source_id):
            if self.event_type in (KAFKA_AUTHENTICATION_CREATE):
                self.save_credentials()
            if self.event_type in (KAFKA_AUTHENTICATION_UPDATE):
                # Because azure auth is split in Sources backend, we need to check both
                # auth and billing when we recieve either auth update or app update event
                updated = any((self.save_billing_source(), self.save_credentials()))
                if updated:
                    LOG.info(f"Source ID {self.source_id} updated")
                    storage.enqueue_source_update(self.source_id)
                else:
                    LOG.info(f"Source ID {self.source_id} not updated. No changes detected.")


class SourceMsgProcessor(KafkaMessageProcessor):
    def __init__(self, msg, event_type, cost_mgmt_id):
        super().__init__(msg, event_type, cost_mgmt_id)
        self.source_id = int(self.value.get("id"))

    def process(self):
        if self.event_type in (KAFKA_SOURCE_UPDATE,):
            if not storage.is_known_source(self.source_id):
                LOG.info("Update event for unknown source id, skipping...")
                return
            updated = self.sources_details()
            if updated:
                LOG.info(f"Source ID {self.source_id} updated")
                storage.enqueue_source_update(self.source_id)
            else:
                LOG.info(f"Source ID {self.source_id} not updated. No changes detected.")

        elif self.event_type in (KAFKA_SOURCE_DESTROY,):
            storage.enqueue_source_delete(self.source_id, self.offset)


def extract_from_header(headers, header_type):
    """Retrieve information from Kafka Headers."""
    for header in headers:
        if header_type in header:
            for item in header:
                if item == header_type:
                    continue
                else:
                    return item.decode("ascii")
    return None


def create_msg_processor(msg, cost_mgmt_id):
    if msg.topic() == Config.SOURCES_TOPIC:
        event_type = extract_from_header(msg.headers(), KAFKA_HDR_EVENT_TYPE)
        LOG.debug(f"event_type: {str(event_type)}")
        if event_type in (KAFKA_APPLICATION_CREATE, KAFKA_APPLICATION_UPDATE, KAFKA_APPLICATION_DESTROY):
            return ApplicationMsgProcessor(msg, event_type, cost_mgmt_id)
        elif event_type in (KAFKA_AUTHENTICATION_CREATE, KAFKA_AUTHENTICATION_UPDATE):
            return AuthenticationMsgProcessor(msg, event_type, cost_mgmt_id)
        elif event_type in (KAFKA_SOURCE_UPDATE, KAFKA_SOURCE_DESTROY):
            return SourceMsgProcessor(msg, event_type, cost_mgmt_id)
        else:
            LOG.debug("Other Message: %s", str(msg))