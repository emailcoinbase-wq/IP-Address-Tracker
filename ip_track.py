import argparse
import os
import sys
import time
import requests

GLOBALPING_API_URL = "https://api.globalping.io/v1/measurements"


def fetch_live_landmarks(target_ip, limit=15, api_token=None):
  payload = {
      "type": "ping",
      "target": target_ip,
      "limit": limit,
      "measurementOptions": {"packets": 3},
  }

  headers = {"Content-Type": "application/json"}
  if api_token:
    headers["Authorization"] = f"Bearer {api_token}"

  print(
      f"[*] Dispatching GlobalPing probes to target {target_ip} (limit:"
      f" {limit})..."
  )
  try:
    response = requests.post(
        GLOBALPING_API_URL, json=payload, headers=headers, timeout=10
    )
  except requests.exceptions.RequestException as e:
    print(f"[-] Network error connecting to GlobalPing API: {e}")
    sys.exit(1)

  if response.status_code == 429:
    print(
        "\n[-] Rate limit exceeded (429). You have exhausted your hourly free"
        " quota for this IP address."
    )
    print(
        "    Tip: Pass a GlobalPing API token using the --token argument or"
        " set the GLOBALPING_TOKEN environment variable."
    )
    sys.exit(1)

  if response.status_code != 202:
    print(
        f"[-] Failed to create measurement: {response.status_code} -"
        f" {response.text}"
    )
    sys.exit(1)

  data = response.json()
  measurement_id = data.get("id")
  print(f"[*] Measurement ID: {measurement_id}. Awaiting global results...")

  result_url = f"{GLOBALPING_API_URL}/{measurement_id}"
  for _ in range(20):
    time.sleep(3)
    try:
      res = requests.get(result_url, headers=headers, timeout=10)
      result_data = res.json()
    except requests.exceptions.RequestException:
      continue

    if result_data.get("status") == "finished":
      raw_results = result_data.get("results", [])
      landmarks = []

      for item in raw_results:
        probe = item.get("probe", {})
        result_block = item.get("result", {})

        if "error" in result_block or not probe.get("latitude") or not probe.get("longitude"):
          continue

        stats = result_block.get("stats", {})
        min_rtt = stats.get("min")

        if min_rtt is not None and min_rtt > 0:
          landmarks.append({
              "name": f"{probe.get('city', 'Unknown')}, {probe.get('country', 'Unknown')}",
              "lat": float(probe["latitude"]),
              "lon": float(probe["longitude"]),
              "min_rtt_ms": float(min_rtt),
          })

      return landmarks

  print("[-] Timed out waiting for GlobalPing results.")
  sys.exit(1)


def estimate_coordinates_weighted(landmarks):
  if not landmarks:
    return {"success": False, "message": "No valid landmark data received."}

  total_weight = 0.0
  weighted_lat = 0.0
  weighted_lon = 0.0

  for lm in landmarks:
    rtt = lm["min_rtt_ms"]
    weight = 1.0 / (rtt**2)
    weighted_lat += lm["lat"] * weight
    weighted_lon += lm["lon"] * weight
    total_weight += weight

  if total_weight == 0:
    return {"success": False, "message": "Calculation weight evaluated to zero."}

  return {
      "lat": weighted_lat / total_weight,
      "lon": weighted_lon / total_weight,
      "success": True,
  }


def main():
  parser = argparse.ArgumentParser(
      description=(
          "Robust Multi-Vantage IP Geolocation using RTT-Weighted Centroid."
      )
  )
  parser.add_argument("target", help="Target IP address or domain to analyze.")
  parser.add_argument(
      "-l",
      "--limit",
      type=int,
      default=15,
      help="Number of global probes to query (default: 15).",
  )
  parser.add_argument(
      "-t",
      "--token",
      help="GlobalPing API token for higher rate limits (or use GLOBALPING_TOKEN env var).",
  )

  args = parser.parse_args()
  api_token = args.token or os.environ.get("GLOBALPING_TOKEN")

  landmarks = fetch_live_landmarks(
      args.target, limit=args.limit, api_token=api_token
  )
  print(
      f"[*] Successfully gathered live RTT metrics from {len(landmarks)}"
      " valid probes."
  )

  print("[*] Computing RTT-weighted geographic center...")
  estimation = estimate_coordinates_weighted(landmarks)

  if estimation["success"]:
    lat = estimation["lat"]
    lon = estimation["lon"]
    maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

    print("\n[+] Estimation Successful:")
    print(f"Estimated Latitude:  {lat:.4f}°")
    print(f"Estimated Longitude: {lon:.4f}°")
    print(f"\nGoogle Maps Link:\n{maps_url}")
  else:
    print(f"[-] Estimation failed: {estimation['message']}")


if __name__ == "__main__":
  main()