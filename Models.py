from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class Apartment(Base):
    __tablename__ = "apartments"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)          # شقة 1 / شقة 2
    rooms = relationship("Room", back_populates="apartment", cascade="all, delete")


class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True)
    apartment_id = Column(Integer, ForeignKey("apartments.id"), nullable=False)
    name = Column(String(100), nullable=False)           # غرفة ماستر / غرفة عادية / الصالة
    room_type = Column(String(20), nullable=False)       # master / regular / hall
    apartment = relationship("Apartment", back_populates="rooms")
    beds = relationship("Bed", back_populates="room", cascade="all, delete")


class Bed(Base):
    __tablename__ = "beds"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    code = Column(String(20), nullable=False)            # M1, R3-علوي, S7-سفلي
    position = Column(String(10), default="single")      # upper / lower / single
    default_price = Column(Float, nullable=False)        # 800 أو 500
    status = Column(String(20), default="vacant")        # vacant / occupied / maintenance
    room = relationship("Room", back_populates="beds")
    contracts = relationship("Contract", back_populates="bed")


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    phone = Column(String(30), default="")
    id_number = Column(String(50), default="")           # رقم الهوية/الإقامة
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    contracts = relationship("Contract", back_populates="tenant")


class Contract(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    bed_id = Column(Integer, ForeignKey("beds.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)               # يُملأ عند الخروج
    monthly_rent = Column(Float, nullable=False)         # قد يختلف عن سعر السرير الافتراضي
    deposit = Column(Float, default=0)                   # التأمين
    deposit_returned = Column(Boolean, default=False)
    status = Column(String(20), default="active")        # active / ended
    notes = Column(Text, default="")
    tenant = relationship("Tenant", back_populates="contracts")
    bed = relationship("Bed", back_populates="contracts")
    payments = relationship("Payment", back_populates="contract")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    contract_id = Column(Integer, ForeignKey("contracts.id"), nullable=False)
    receipt_no = Column(String(30), unique=True, nullable=False)  # SKN-2026-0001
    month = Column(String(7), nullable=False)            # "2026-07"
    amount = Column(Float, nullable=False)
    method = Column(String(30), default="cash")          # cash / transfer / other
    paid_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, default="")
    contract = relationship("Contract", back_populates="payments")


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    action = Column(String(300), nullable=False)          # وصف العملية بالعربي
    created_at = Column(DateTime, default=datetime.utcnow)
