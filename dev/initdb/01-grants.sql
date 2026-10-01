-- 开发环境专用。pytest 的迁移验证会在独立测试库上执行建表与回退，
-- 这里把测试库的权限授予应用账号；正式环境不需要这一步。
-- 注意：本文件只在数据目录首次初始化时执行，已有数据卷不会重复执行。
-- 库名里的下划线要转义，否则 MySQL 会当成通配符匹配（等同于放开同类库名）。
GRANT ALL PRIVILEGES ON `pulse\_lifecycle\_dev\_test`.* TO 'pulse_dev'@'%';
FLUSH PRIVILEGES;
