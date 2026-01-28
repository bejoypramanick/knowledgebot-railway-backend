# Database Import Architecture Guidelines

## 🎯 **Core Principle**

**ONLY DAO layers should directly import database connections.** All routers and services must use service layers or service factories.

## ✅ **Allowed Patterns**

### **DAO Layer** (✅ ONLY place for direct DB imports)
```python
# dao/some_dao.py
from shared.db import get_db_connection

class SomeDAO:
    def __init__(self, connection):
        self.conn = connection
    
    async def get_data(self):
        return await self.conn.fetch("SELECT * FROM table")
```

### **Service Layer** (✅ Internal DB management)
```python
# servcie/some_service.py
from shared.db import get_db_connection

class SomeService:
    @classmethod
    async def get_data(cls):
        async with get_db_connection() as conn:
            dao = SomeDAO(conn)
            return await dao.get_data()
```

### **Service Factory** (✅ Only place besides DAOs for DB imports)
```python
# servcie/service_factory.py
from shared.db import get_db_connection

class ServiceFactory:
    @staticmethod
    async def create_some_service():
        async with get_db_connection() as conn:
            dao = SomeDAO(conn)
            return SomeService(dao)
```

### **Router Layer** (✅ NO database imports)
```python
# routers/some_router.py
from ..servcie.service_factory import ServiceFactory

@router.get("/")
async def get_data():
    service = await ServiceFactory.create_some_service()
    return await service.get_data()
```

## ❌ **Forbidden Patterns**

### **❌ Router with Database Import**
```python
# FORBIDDEN
from shared.db import get_db_connection

@router.get("/")
async def get_data():
    async with get_db_connection() as conn:
        # This is WRONG!
```

### **❌ Service with Direct DB Import (unless using class methods)**
```python
# FORBIDDEN
from shared.db import get_db_connection

class SomeService:
    def __init__(self):
        # Don't import DB here unless using class methods
```

## 🏗️ **Architecture Layers**

1. **Router Layer** - HTTP endpoints, NO database imports
2. **Service Layer** - Business logic, internal DB management
3. **DAO Layer** - Database operations, ONLY place for direct DB imports
4. **Database Layer** - Connection management

## 📋 **Checklist for New Code**

- [ ] Router has NO `from shared.db import get_db_connection`
- [ ] Router has NO `from ..core.database import get_railway_db`
- [ ] Service uses class methods OR service factory pattern
- [ ] DAO is the ONLY layer with direct database imports
- [ ] All database operations go through DAO layer

## 🔧 **Migration Strategy**

When fixing existing violations:

1. **Create service layer** if missing
2. **Update service** to use class methods with internal DB
3. **Create service factory** for dependency injection
4. **Update router** to use service factory
5. **Remove all database imports** from router

## 🚨 **Enforcement**

This architecture will be enforced via:
- Code reviews
- Automated linting rules
- Git pre-commit hooks
- Architecture compliance checks

## 📞 **Support**

For questions about this architecture:
1. Check existing examples in the codebase
2. Review the service factory patterns
3. Consult with the architecture team

---

**Remember: ONLY DAO layers should directly import database connections!**
