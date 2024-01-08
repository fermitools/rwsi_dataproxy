create table if not exists history
(
    service varchar(100),
    t real,
    f1 real,    f2 real,    f3 real,
    wait_time_avg   real,   wait_time_max   real, 
    process_time_avg   real,   process_time_max   real, 
    active_connections   int,   queued_connections   int,
    primary key ( service, t )
);

create table if not exists request_history
(
    service varchar(100),
    t real,
    wait_time real,
    process_time real,
    http_status int,
    received_count int,
    sent_count int,
    data_size int
);
    
    
    
