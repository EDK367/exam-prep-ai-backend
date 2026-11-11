"""
Test factories using factory_boy for generating mock database records.
"""
import uuid
from datetime import datetime, timedelta

import factory
from app.modules.users.models import User
from app.modules.billing.models import Plan, UserSubscription
from app.modules.documents.models import Document
from app.core.enums import DocumentStatus


class UserFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session = None  # Will be set in tests
        sqlalchemy_session_persistence = "commit"

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Faker("name")
    supabase_id = factory.Sequence(lambda n: f"supabase_{n}")
    is_active = True


class PlanFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Plan
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "commit"

    id = factory.LazyFunction(uuid.uuid4)
    name = "Pro"
    max_tokens = 500000
    max_uploads = 100
    max_test = 50
    model = "gpt-4o"


class UserSubscriptionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = UserSubscription
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "commit"

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(PlanFactory)
    status = "active"
    starter_at = factory.LazyFunction(datetime.utcnow)
    expires_at = factory.LazyFunction(lambda: datetime.utcnow() + timedelta(days=30))


class DocumentFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Document
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "commit"

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    filename = factory.Faker("file_name", extension="pdf")
    storage_path = factory.Sequence(lambda n: f"documents/fake_{n}.pdf")
    size_types = 1024
    status = DocumentStatus.COMPLETED.value
    page_count = 10
    chunk_count = 15
