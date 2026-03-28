use chrono::{DateTime, FixedOffset, Timelike};
use clap::{Parser, Subcommand};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Parser, Debug)]
#[command(author, version, about = "Immich Album Fixup Tool", long_about = None)]
struct Args {
    /// Immich Server URL (e.g., http://server.url:1234)
    #[arg(short, long)]
    server: String,

    /// Immich API Key
    #[arg(long)]
    api_key: String,

    /// Path to the CSV metadata file (also used to derive Album Name)
    #[arg(short, long)]
    metadata: PathBuf,

    /// Run the script without modifying data
    #[arg(long, default_value_t = false, global = true)]
    dry_run: bool,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Fix metadata (datetime and tags) based on the CSV
    FixMetadata,
    /// Stack matching photos and videos into Live Photos based on filenames
    FixLivephotos,
    /// Run both metadata fixup and live photo stacking
    Fix,
}

#[derive(Debug, Deserialize)]
struct CsvRow {
    #[serde(rename = "Date taken")]
    date_taken: Option<String>,
    #[serde(rename = "Time taken")]
    time_taken: Option<String>,
    #[serde(rename = "Timezone")]
    timezone: Option<String>,
    #[serde(rename = "Filename")]
    filename: String,
    #[serde(rename = "Size")]
    size: String,
    #[serde(rename = "Shared by")]
    shared_by: Option<String>,
}

fn extract_album_name(path: &Path) -> anyhow::Result<String> {
    let file_stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or_else(|| anyhow::anyhow!("Invalid metadata filename format"))?;

    if let Some(album) = file_stem.strip_suffix("-unified") {
        return Ok(album.to_string());
    }

    if let Some((album, _timestamp)) = file_stem.rsplit_once('_') {
        return Ok(album.to_string());
    }

    Ok(file_stem.to_string())
}

fn parse_datetime(date: &str, time: &str, tz: &str) -> Option<DateTime<FixedOffset>> {
    let time_clean = time.replace('\u{202F}', " ");
    let tz_clean = tz.replace("GMT", "");
    let dt_str = format!("{} {} {}", date, time_clean, tz_clean);

    if let Ok(dt) = DateTime::parse_from_str(&dt_str, "%b %d, %Y %a, %I:%M %p %:z") {
        return Some(dt);
    }
    if let Ok(dt) = DateTime::parse_from_str(&dt_str, "%b %d, %Y %I:%M %p %:z") {
        return Some(dt);
    }
    None
}

fn parse_size(size_str: &str) -> Option<(u32, u32)> {
    let parts: Vec<&str> = size_str.split('×').collect();
    if parts.len() == 2 {
        let w = parts[0].trim().parse().ok()?;
        let h = parts[1].trim().parse().ok()?;
        return Some((w, h));
    }
    None
}

fn filenames_match(f1: &str, f2: &str) -> bool {
    let s1 = f1.to_lowercase();
    let s2 = f2.to_lowercase();
    if s1 == s2 {
        return true;
    }

    let stem1 = std::path::Path::new(&s1)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(&s1);
    let stem2 = std::path::Path::new(&s2)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(&s2);
    stem1 == stem2
}

fn run_fix_metadata(
    client: &reqwest::blocking::Client,
    api_base: &str,
    args: &Args,
    assets: &[serde_json::Value],
) -> anyhow::Result<()> {
    println!("\n--- Starting Metadata Fixup ---");
    println!("Loading metadata from {:?}", args.metadata);
    let mut reader = csv::ReaderBuilder::new()
        .flexible(true)
        .from_path(&args.metadata)?;
    let records: Vec<CsvRow> = reader
        .deserialize()
        .filter_map(|r| {
            r.map_err(|e| println!("Warning: skipping unparseable row: {}", e))
                .ok()
        })
        .collect();
    println!("Loaded {} rows from CSV.", records.len());

    for row in records {
        let (csv_w, csv_h) = parse_size(&row.size).unwrap_or((0, 0));

        let matched_asset = assets.iter().find(|a| {
            let orig_name = a
                .get("originalFileName")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let exif = a.get("exifInfo").and_then(|v| v.as_object());
            let api_w = exif
                .and_then(|e| e.get("exifImageWidth").or_else(|| e.get("imageWidth")))
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as u32;
            let api_h = exif
                .and_then(|e| e.get("exifImageHeight").or_else(|| e.get("imageHeight")))
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as u32;

            filenames_match(orig_name, &row.filename)
                && ((csv_w == api_w && csv_h == api_h) || (csv_w == api_h && csv_h == api_w))
        });

        if let Some(asset) = matched_asset {
            let asset_id = asset
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("UNKNOWN");
            let exif = asset.get("exifInfo").and_then(|v| v.as_object());

            let mut payload = serde_json::Map::new();
            let mut updates = Vec::new();
            let mut new_tags_to_add = Vec::new();

            // Handle Date
            if let (Some(d), Some(t), Some(tz)) = (&row.date_taken, &row.time_taken, &row.timezone)
                && let Some(mut new_dt) = parse_datetime(d, t, tz)
            {
                let old_time_str = exif
                    .and_then(|e| e.get("dateTimeOriginal"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if let Ok(old_dt) = DateTime::parse_from_rfc3339(old_time_str) {
                    new_dt = new_dt.with_second(old_dt.second()).unwrap_or(new_dt);
                    new_dt = new_dt
                        .with_nanosecond(old_dt.nanosecond())
                        .unwrap_or(new_dt);
                }
                let iso_time = new_dt.to_rfc3339();
                if old_time_str != iso_time {
                    updates.push(format!(
                        "DateTimeOriginal: '{}' -> '{}'",
                        old_time_str, iso_time
                    ));
                    payload.insert("dateTimeOriginal".to_string(), serde_json::json!(iso_time));
                }
            }

            // Handle Tags
            if let Some(shared_by) = &row.shared_by {
                let new_tag = format!("Uploaded by: {}", shared_by);
                let old_tags = asset
                    .get("tags")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|t| {
                                t.get("value").or(t.get("name")).and_then(|v| v.as_str())
                            })
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .unwrap_or_else(|| "None".to_string());

                if !old_tags.contains(&new_tag) {
                    updates.push(format!(
                        "Tags: '{}' -> '{}, {}'",
                        old_tags, old_tags, new_tag
                    ));
                    new_tags_to_add.push(new_tag);
                }
            }

            if !updates.is_empty() {
                println!("\n[{}] matched (ID: {})", row.filename, asset_id);
                for u in &updates {
                    println!("  - {}", u);
                }

                if !args.dry_run {
                    if !payload.is_empty() {
                        let update_url = format!("{}/assets/{}", api_base, asset_id);
                        let res = client
                            .put(&update_url)
                            .header("x-api-key", &args.api_key)
                            .header("Accept", "application/json")
                            .json(&payload)
                            .send()?;
                        if res.status().is_success() {
                            println!("  [SUCCESS] Metadata updated.");
                        } else {
                            println!(
                                "  [ERROR] Failed to update: HTTP {} | {:?}",
                                res.status(),
                                res.text()
                            );
                        }
                    }
                    if !new_tags_to_add.is_empty() {
                        let tag_upsert_url = format!("{}/tags", api_base);
                        let tag_upsert_res = client
                            .put(&tag_upsert_url)
                            .header("x-api-key", &args.api_key)
                            .header("Accept", "application/json")
                            .json(&serde_json::json!({ "tags": new_tags_to_add }))
                            .send()?;
                        if tag_upsert_res.status().is_success() {
                            let tag_json: Vec<serde_json::Value> = tag_upsert_res.json()?;
                            let tag_ids: Vec<&str> = tag_json
                                .iter()
                                .filter_map(|t| t.get("id").and_then(|id| id.as_str()))
                                .collect();
                            if !tag_ids.is_empty() {
                                let tag_assets_url = format!("{}/tags/assets", api_base);
                                let tag_assets_res = client.put(&tag_assets_url).header("x-api-key", &args.api_key).header("Accept", "application/json").json(&serde_json::json!({ "assetIds": [asset_id], "tagIds": tag_ids })).send()?;
                                if tag_assets_res.status().is_success() {
                                    println!("  [SUCCESS] Tags added.");
                                }
                            }
                        }
                    }
                }
            } else {
                println!("[{}] matched - No metadata changes needed.", row.filename);
            }
        } else {
            println!(
                "\n[Warning] No matching asset found for CSV row: {} (Size: {})",
                row.filename, row.size
            );
        }
    }
    Ok(())
}

fn run_fix_livephotos(
    client: &reqwest::blocking::Client,
    api_base: &str,
    args: &Args,
    assets: &[serde_json::Value],
) -> anyhow::Result<()> {
    println!("\n--- Starting Live Photo Stacking ---");
    println!("Finding Live Photo pairs...");
    let mut videos: HashMap<String, String> = HashMap::new();
    let mut photos: Vec<(String, String, String)> = Vec::new(); // (asset_id, originalFileName, stem)

    // Separate the album's assets into videos and photos, extracting their stems
    for asset in assets {
        let asset_id = asset.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let asset_type = asset.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let orig_name = asset
            .get("originalFileName")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        if asset_id.is_empty() || orig_name.is_empty() {
            continue;
        }

        // Determine base filename without extension to use as a matching key
        let stem = Path::new(orig_name)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or(orig_name)
            .to_lowercase();

        if asset_type == "VIDEO" {
            videos.insert(stem, asset_id.to_string());
        } else if asset_type == "IMAGE" {
            photos.push((asset_id.to_string(), orig_name.to_string(), stem));
        }
    }

    // Find intersections and update photos
    let mut pairs_found = 0;
    for (photo_id, photo_name, photo_stem) in photos {
        if let Some(video_id) = videos.get(&photo_stem) {
            pairs_found += 1;
            println!(
                "Found pair: Photo '{}' (ID: {}) <-> Video ID: {}",
                photo_name, photo_id, video_id
            );

            if !args.dry_run {
                let update_url = format!("{}/assets/{}", api_base, photo_id);

                let payload = serde_json::json!({
                    "livePhotoVideoId": video_id
                });

                let res = client
                    .put(&update_url)
                    .header("x-api-key", &args.api_key)
                    .header("Accept", "application/json")
                    .json(&payload)
                    .send()?;

                if res.status().is_success() {
                    println!("  [SUCCESS] Linked Live Photo.");
                } else {
                    println!(
                        "  [ERROR] Failed to link Live Photo: HTTP {} | {:?}",
                        res.status(),
                        res.text()
                    );
                }
            } else {
                println!(
                    "  [Dry Run] Would link video {} to photo {}",
                    video_id, photo_id
                );
            }
        }
    }

    println!(
        "Finished processing Live Photos. Found {} pairs.",
        pairs_found
    );
    Ok(())
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let api_base = format!("{}/api", args.server.trim_end_matches('/'));
    let client = reqwest::blocking::Client::new();

    // 1. Extract Target Album Name
    let target_album_name = extract_album_name(&args.metadata)?;
    println!("Extracted Target Album Name: '{}'", target_album_name);

    // 2. Fetch Albums & Find Target
    let albums_url = format!("{}/albums", api_base);
    let albums_res = client
        .get(&albums_url)
        .header("x-api-key", &args.api_key)
        .header("Accept", "application/json")
        .send();

    let albums_url_fallback = format!("{}/album", api_base);
    let albums_resp: Vec<serde_json::Value> = if let Ok(res) = albums_res {
        if res.status().is_success() {
            res.json()?
        } else {
            client
                .get(&albums_url_fallback)
                .header("x-api-key", &args.api_key)
                .header("Accept", "application/json")
                .send()?
                .json()?
        }
    } else {
        client
            .get(&albums_url_fallback)
            .header("x-api-key", &args.api_key)
            .header("Accept", "application/json")
            .send()?
            .json()?
    };

    let album_id = albums_resp
        .into_iter()
        .find(|a| a.get("albumName").and_then(|v| v.as_str()) == Some(target_album_name.as_str()))
        .and_then(|a| a.get("id").and_then(|v| v.as_str()).map(|s| s.to_string()))
        .ok_or_else(|| anyhow::anyhow!("Album '{}' not found", target_album_name))?;

    // 3. Set Album Sort Order
    if !args.dry_run {
        println!(
            "Setting album '{}' display order to oldest first...",
            target_album_name
        );
        let update_album_url = format!("{}/albums/{}", api_base, album_id);
        let res = client
            .patch(&update_album_url)
            .header("x-api-key", &args.api_key)
            .header("Accept", "application/json")
            .json(&serde_json::json!({
                "order": "asc"
            }))
            .send()?;

        if res.status().is_success() {
            println!("  [SUCCESS] Album sort order updated.");
        } else {
            println!(
                "  [WARNING] Failed to update album sort order: HTTP {} | {:?}",
                res.status(),
                res.text()
            );
        }
    } else {
        println!(
            "[Dry Run] Would have set album '{}' display order to oldest first.",
            target_album_name
        );
    }

    // 4. Fetch Assets for Album
    println!("Found album ID: {}. Fetching assets...", album_id);
    let album_info_url = format!("{}/albums/{}", api_base, album_id);
    let mut assets_opt = None;

    if let Ok(res) = client
        .get(&album_info_url)
        .header("x-api-key", &args.api_key)
        .header("Accept", "application/json")
        .send()
        && res.status().is_success()
    {
        let json: serde_json::Value = res.json()?;
        assets_opt = json.get("assets").and_then(|v| v.as_array()).cloned();
    }

    if assets_opt.is_none() {
        let fallback_url = format!("{}/album/{}", api_base, album_id);
        let json: serde_json::Value = client
            .get(&fallback_url)
            .header("x-api-key", &args.api_key)
            .header("Accept", "application/json")
            .send()?
            .json()?;
        assets_opt = json.get("assets").and_then(|v| v.as_array()).cloned();
    }

    let assets =
        assets_opt.ok_or_else(|| anyhow::anyhow!("Could not find assets payload for album."))?;
    println!("Found {} assets in album.", assets.len());

    // 5. Execute Subcommand Logic
    match args.command {
        Commands::FixMetadata => {
            run_fix_metadata(&client, &api_base, &args, &assets)?;
        }
        Commands::FixLivephotos => {
            run_fix_livephotos(&client, &api_base, &args, &assets)?;
        }
        Commands::Fix => {
            run_fix_metadata(&client, &api_base, &args, &assets)?;
            run_fix_livephotos(&client, &api_base, &args, &assets)?;
        }
    }

    Ok(())
}
