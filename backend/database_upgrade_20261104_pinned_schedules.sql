-- 先在应用实际使用的数据库执行，再部署后端和前端。
USE cvonto_nurse_station;
CREATE TABLE IF NOT EXISTS nurse_pinned_schedules (
    nurse_id VARCHAR(50) NOT NULL,
    clinic_dept VARCHAR(20) NOT NULL,
    clinic_label VARCHAR(100) NOT NULL,
    time_desc VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (nurse_id, clinic_dept, clinic_label, time_desc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
COMMENT='护士置顶号别（跨日期，区分午别）';
