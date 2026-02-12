//! Minimal test to verify pgwire-replication works without PyO3
//!
//! Run with: cargo run --example test_replication

use anyhow::Context;
use pgwire_replication::{
    client::ReplicationEvent, Lsn, ReplicationClient, ReplicationConfig, TlsConfig,
};
use tokio_postgres::NoTls;

async fn setup_database() -> anyhow::Result<(String, u16)> {
    // Use Docker to start a PostgreSQL instance
    println!("Starting PostgreSQL container...");
    let output = std::process::Command::new("docker")
        .args(&[
            "run",
            "-d",
            "--rm",
            "-e",
            "POSTGRES_PASSWORD=test",
            "-e",
            "POSTGRES_USER=test",
            "-e",
            "POSTGRES_DB=testdb",
            "-p",
            "0:5432",
            "postgres:18.1-alpine",
            "postgres",
            "-c",
            "wal_level=logical",
            "-c",
            "max_replication_slots=4",
            "-c",
            "max_wal_senders=4",
        ])
        .output()
        .context("Failed to start docker container")?;

    let container_id = String::from_utf8(output.stdout)?.trim().to_string();
    println!("Container ID: {}", container_id);

    // Wait for container to be ready
    tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;

    // Get the mapped port
    let output = std::process::Command::new("docker")
        .args(&["port", &container_id, "5432"])
        .output()
        .context("Failed to get port")?;

    let port_mapping = String::from_utf8(output.stdout)?;
    let port: u16 = port_mapping
        .split(':')
        .last()
        .context("Invalid port format")?
        .trim()
        .parse()
        .context("Failed to parse port")?;

    println!("Postgres listening on port: {}", port);

    // Connect and setup
    let dsn = format!(
        "host=localhost port={} user=test password=test dbname=testdb",
        port
    );
    let (client, connection) = tokio_postgres::connect(&dsn, NoTls).await?;

    tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("Connection error: {}", e);
        }
    });

    println!("Creating table...");
    client
        .execute("CREATE TABLE test (id INT PRIMARY KEY, val TEXT)", &[])
        .await?;
    client
        .execute("ALTER TABLE test REPLICA IDENTITY FULL", &[])
        .await?;

    println!("Creating publication...");
    client
        .execute("CREATE PUBLICATION test_pub FOR ALL TABLES", &[])
        .await?;

    println!("Creating replication slot...");
    client
        .execute(
            "SELECT pg_create_logical_replication_slot('test_slot', 'pgoutput')",
            &[],
        )
        .await?;

    // Get slot info
    let row = client.query_one(
        "SELECT restart_lsn::text, confirmed_flush_lsn::text FROM pg_replication_slots WHERE slot_name = 'test_slot'",
        &[],
    ).await?;

    let restart: Option<String> = row.get(0);
    let confirmed: Option<String> = row.get(1);

    println!("Slot created:");
    println!("  restart_lsn: {:?}", restart);
    println!("  confirmed_flush_lsn: {:?}", confirmed);

    println!("\nInserting test data...");
    client
        .execute("INSERT INTO test VALUES (1, 'hello')", &[])
        .await?;
    client
        .execute("INSERT INTO test VALUES (2, 'world')", &[])
        .await?;
    println!("Inserted 2 rows");

    // Check slot again
    let row = client.query_one(
        "SELECT restart_lsn::text, confirmed_flush_lsn::text FROM pg_replication_slots WHERE slot_name = 'test_slot'",
        &[],
    ).await?;

    let restart: Option<String> = row.get(0);
    let confirmed: Option<String> = row.get(1);

    println!("\nSlot after insert:");
    println!("  restart_lsn: {:?}", restart);
    println!("  confirmed_flush_lsn: {:?}", confirmed);

    Ok(("localhost".to_string(), port))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let (host, port) = setup_database().await?;

    println!("\n=== Starting Replication Client ===\n");

    let config = ReplicationConfig {
        host,
        port,
        user: "test".to_string(),
        password: "test".to_string(),
        database: "testdb".to_string(),
        tls: TlsConfig::disabled(),
        slot: "test_slot".to_string(),
        publication: "test_pub".to_string(),
        start_lsn: Lsn::ZERO, // Use 0 to start from slot's position
        stop_at_lsn: None,
        status_interval: std::time::Duration::from_secs(10),
        idle_wakeup_interval: std::time::Duration::from_secs(10),
        buffer_events: 8192,
    };

    println!("Connecting to replication stream...");
    let mut client = ReplicationClient::connect(config).await?;
    println!("Connected successfully!\n");

    let mut message_count = 0;
    let timeout = tokio::time::Duration::from_secs(15);
    let start = tokio::time::Instant::now();

    loop {
        if start.elapsed() > timeout {
            println!("\nTimeout reached after {} seconds", timeout.as_secs());
            break;
        }

        match tokio::time::timeout(tokio::time::Duration::from_secs(2), client.recv()).await {
            Ok(Ok(Some(event))) => match event {
                ReplicationEvent::XLogData {
                    wal_start,
                    wal_end,
                    data,
                    ..
                } => {
                    println!(
                        "📦 XLogData: wal_start={} wal_end={} bytes={}",
                        wal_start,
                        wal_end,
                        data.len()
                    );
                    message_count += 1;
                    client.update_applied_lsn(wal_end);

                    if message_count >= 2 {
                        println!("\n✅ SUCCESS: Received {} messages!", message_count);
                        break;
                    }
                }
                ReplicationEvent::KeepAlive {
                    wal_end,
                    reply_requested,
                    ..
                } => {
                    println!(
                        "💓 KeepAlive: wal_end={} reply_requested={}",
                        wal_end, reply_requested
                    );
                }
                ReplicationEvent::Begin { xid, .. } => {
                    println!("🔵 Begin: xid={}", xid);
                }
                ReplicationEvent::Commit { end_lsn, .. } => {
                    println!("🟢 Commit: end_lsn={}", end_lsn);
                }
                ReplicationEvent::Message {
                    prefix, content, ..
                } => {
                    println!("📨 Message: prefix={} bytes={}", prefix, content.len());
                }
                ReplicationEvent::StoppedAt { reached } => {
                    println!("🛑 StoppedAt: {}", reached);
                    break;
                }
            },
            Ok(Ok(None)) => {
                println!("Stream ended");
                break;
            }
            Ok(Err(e)) => {
                eprintln!("❌ Replication error: {}", e);
                return Err(e.into());
            }
            Err(_) => {
                // Timeout on recv - continue
            }
        }
    }

    if message_count == 0 {
        println!("\n❌ FAILED: Received 0 XLogData messages");
    }

    Ok(())
}
