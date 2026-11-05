import React, { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Building2, MapPin, Search, LocateFixed, IndianRupee, ArrowRight, LoaderCircle } from "lucide-react";
import { Card, Spinner, formatINR } from "./Shared.jsx";

const PUNE_CENTER = [18.5204, 73.8567];
const DEFAULT_ZOOM = 12;

const MOCK_PROPERTIES = [
  {
    id: "PRP-2041",
    latitude: 18.5204,
    longitude: 73.8567,
    location: "Shivaji Nagar, Pune",
    propertyType: "Apartment",
    bedrooms: 2,
    bathrooms: 2,
    areaSqft: 980,
    price: 7600000,
    age: 8,
  },
  {
    id: "PRP-1087",
    latitude: 18.5539,
    longitude: 73.9279,
    location: "Baner, Pune",
    propertyType: "Villa",
    bedrooms: 4,
    bathrooms: 3,
    areaSqft: 2450,
    price: 25500000,
    age: 7,
  },
  {
    id: "PRP-3312",
    latitude: 18.5167,
    longitude: 73.7765,
    location: "Kothrud, Pune",
    propertyType: "Apartment",
    bedrooms: 3,
    bathrooms: 2,
    areaSqft: 1450,
    price: 11350000,
    age: 10,
  },
  {
    id: "PRP-4561",
    latitude: 18.5928,
    longitude: 73.7386,
    location: "Wakad, Pune",
    propertyType: "Townhouse",
    bedrooms: 3,
    bathrooms: 3,
    areaSqft: 1680,
    price: 14900000,
    age: 6,
  },
  {
    id: "PRP-7784",
    latitude: 18.5621,
    longitude: 73.8117,
    location: "Hinjewadi, Pune",
    propertyType: "Flat",
    bedrooms: 2,
    bathrooms: 2,
    areaSqft: 1180,
    price: 8900000,
    age: 5,
  },
];

export function predictProperty(propertyData) {
  const payload = {
    location: propertyData?.location || "Unknown",
    latitude: propertyData?.latitude ?? null,
    longitude: propertyData?.longitude ?? null,
    propertyType: propertyData?.propertyType || "Unknown",
    bedrooms: propertyData?.bedrooms ?? null,
    bathrooms: propertyData?.bathrooms ?? null,
    areaSqft: propertyData?.areaSqft ?? null,
    age: propertyData?.age ?? null,
  };

  return payload;
}

const markerIcon = (isSelected = false, isActive = false) =>
  L.divIcon({
    className: "property-map-marker",
    html: `
      <span
        class="marker-pin ${isSelected ? "marker-pin-selected" : ""} ${isActive ? "marker-pin-active" : ""}"
      ></span>
    `,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    popupAnchor: [0, -10],
  });

function MapController({ center, onMapReady, onLocationSelect }) {
  const map = useMap();

  useEffect(() => {
    onMapReady(map);
  }, [map, onMapReady]);

  useEffect(() => {
    if (center) {
      map.flyTo(center, Math.max(map.getZoom(), DEFAULT_ZOOM), {
        animate: true,
        duration: 1.2,
      });
    }
  }, [center, map]);

  useMapEvents({
    click(event) {
      const nextLocation = {
        lat: Number(event.latlng.lat.toFixed(6)),
        lng: Number(event.latlng.lng.toFixed(6)),
      };
      onLocationSelect(nextLocation);
    },
  });

  return null;
}

export default function PropertyMap() {
  const [query, setQuery] = useState("Baner, Pune");
  const [selectedLocation, setSelectedLocation] = useState({
    lat: 18.5204,
    lng: 73.8567,
    label: "Pune, Maharashtra, India",
  });
  const [selectedProperty, setSelectedProperty] = useState(MOCK_PROPERTIES[1]);
  const [mapInstance, setMapInstance] = useState(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [predictionNotice, setPredictionNotice] = useState("");

  const mapCenter = useMemo(
    () => [selectedLocation.lat, selectedLocation.lng],
    [selectedLocation.lat, selectedLocation.lng]
  );

  useEffect(() => {
    if (mapInstance) {
      mapInstance.invalidateSize();
    }
  }, [mapInstance]);

  const handleMapLocationSelection = (nextLocation) => {
    setSelectedLocation({
      ...nextLocation,
      label: `Selected location (${nextLocation.lat.toFixed(4)}, ${nextLocation.lng.toFixed(4)})`,
    });
    setSelectedProperty(null);
    setPredictionNotice("");
    setError("");
  };

  const handleSearch = async () => {
    if (!query.trim()) {
      setError("Please enter a location to search.");
      return;
    }

    setSearching(true);
    setError("");
    setPredictionNotice("");

    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`,
        {
          headers: {
            Accept: "application/json",
          },
        }
      );

      if (!response.ok) {
        throw new Error("Unable to resolve this location right now.");
      }

      const results = await response.json();
      const match = results?.[0];

      if (!match) {
        throw new Error("No matching location was found. Try a different area in Pune.");
      }

      const lat = Number(match.lat);
      const lng = Number(match.lon);

      setSelectedLocation({
        lat,
        lng,
        label: match.display_name,
      });
      setSelectedProperty(null);
    } catch (searchError) {
      setError(searchError.message || "Location search failed.");
    } finally {
      setSearching(false);
    }
  };

  const useSelectedLocation = () => {
    const payload = {
      location: selectedLocation.label || "Custom selected location",
      latitude: selectedLocation.lat,
      longitude: selectedLocation.lng,
    };

    setPredictionNotice(`Selected location ready for ML input: ${payload.location}`);
    return payload;
  };

  const activeProperty = selectedProperty || null;

  return (
    <Card className="overflow-hidden border border-[#e5dfd2] bg-card shadow-card">
      <div className="border-b border-[#f0ebdf] px-5 py-4 md:px-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Property intelligence map</p>
            <h2 className="mt-1 font-display text-2xl font-bold text-ink-900">Interactive market map</h2>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full bg-teal-50 px-3 py-1.5 text-xs font-semibold text-teal-700">
            <MapPin size={14} /> Pune, Maharashtra
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-3 md:flex-row">
          <label className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" size={17} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") handleSearch();
              }}
              placeholder="Search by location, e.g. Baner, Pune"
              className="w-full min-w-0 rounded-xl border border-[#d9d1c4] bg-[#f9f7f3] py-3 pl-11 pr-4 text-sm leading-5 text-ink-900 shadow-sm placeholder:text-ink-400"
            />
          </label>
          <button
            onClick={handleSearch}
            disabled={searching}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-teal px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {searching ? <LoaderCircle size={16} className="animate-spin" /> : <Search size={16} />} 
            {searching ? "Searching" : "Search"}
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </div>
        )}
      </div>

      <div className="grid gap-5 p-5 md:p-6 xl:grid-cols-[1.7fr_0.95fr]">
        <div className="space-y-4">
          <div className="overflow-hidden rounded-2xl border border-[#e5dfd2] bg-slate-50">
            <div className="h-[440px] w-full">
              <MapContainer center={PUNE_CENTER} zoom={DEFAULT_ZOOM} scrollWheelZoom className="h-full w-full leaflet-container-custom">
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />

                <MapController
                  center={mapCenter}
                  onMapReady={setMapInstance}
                  onLocationSelect={handleMapLocationSelection}
                />

                {MOCK_PROPERTIES.map((property) => (
                  <Marker
                    key={property.id}
                    position={[property.latitude, property.longitude]}
                    icon={markerIcon(Boolean(activeProperty && activeProperty.id === property.id), Boolean(activeProperty && activeProperty.id === property.id))}
                    eventHandlers={{
                      click: () => {
                        setSelectedProperty(property);
                        setSelectedLocation({
                          lat: property.latitude,
                          lng: property.longitude,
                          label: property.location,
                        });
                        setPredictionNotice("");
                      },
                    }}
                  >
                    <Popup>
                      <div className="min-w-[210px] space-y-2 p-1 text-sm text-slate-700">
                        <div className="flex items-center justify-between gap-2">
                          <span className="rounded-full bg-teal-50 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-teal-700">
                            {property.propertyType}
                          </span>
                          <span className="text-xs font-semibold text-ink-700">{property.location}</span>
                        </div>
                        <ul className="space-y-1 text-xs text-slate-600">
                          <li>Bedrooms: {property.bedrooms}</li>
                          <li>Area: {property.areaSqft.toLocaleString("en-IN")} sq.ft</li>
                          <li>Listed price: {formatINR(property.price)}</li>
                        </ul>
                        <button
                          type="button"
                          onClick={() => {
                            const payload = predictProperty(property);
                            setPredictionNotice(`ML-ready payload prepared for ${payload.location}`);
                            console.info("PropIntel prediction payload ready:", payload);
                          }}
                          className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent-teal px-3 py-2 text-xs font-semibold text-white"
                        >
                          Predict Price <ArrowRight size={14} />
                        </button>
                      </div>
                    </Popup>
                  </Marker>
                ))}

                <Marker
                  position={[selectedLocation.lat, selectedLocation.lng]}
                  icon={markerIcon(true, false)}
                >
                  <Popup>
                    <div className="space-y-1 text-sm">
                      <p className="font-semibold text-ink-900">Selected location</p>
                      <p className="text-slate-600">Lat: {selectedLocation.lat}</p>
                      <p className="text-slate-600">Lng: {selectedLocation.lng}</p>
                    </div>
                  </Popup>
                </Marker>
              </MapContainer>
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-[#e8e0d0] bg-[#faf7f0] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-ink-500">Selected location</p>
              <p className="mt-1 break-words font-display text-xl font-bold leading-snug text-ink-900">{selectedLocation.label}</p>
            </div>
            <button
              type="button"
              onClick={useSelectedLocation}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent-teal px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-700"
            >
              <LocateFixed size={16} /> Use Selected Location
            </button>
          </div>

          {predictionNotice && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {predictionNotice}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <Card className="p-4">
            <div className="flex items-center gap-2 text-ink-900">
              <Building2 size={18} className="text-accent-teal" />
              <h3 className="font-display text-xl font-bold">Property snapshot</h3>
            </div>

            {activeProperty ? (
              <div className="mt-4 space-y-4">
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Property type</p>
                  <p className="mt-1 text-lg font-bold text-ink-900">{activeProperty.propertyType}</p>
                </div>

                <div className="space-y-3 text-sm text-slate-600">
                  <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                    <span>Location</span>
                    <span className="min-w-0 break-words text-right font-semibold text-ink-900">{activeProperty.location}</span>
                  </div>
                  <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                    <span>Bedrooms</span>
                    <span className="min-w-0 break-words text-right font-semibold text-ink-900">{activeProperty.bedrooms}</span>
                  </div>
                  <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                    <span>Area</span>
                    <span className="min-w-0 break-words text-right font-semibold text-ink-900">{activeProperty.areaSqft.toLocaleString("en-IN")} sq.ft</span>
                  </div>
                  <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                    <span>Price</span>
                    <span className="min-w-0 break-words text-right font-semibold text-ink-900">{formatINR(activeProperty.price)}</span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    const payload = predictProperty(activeProperty);
                    setPredictionNotice(`ML-ready payload prepared for ${payload.location}`);
                    console.info("PropIntel prediction payload ready:", payload);
                  }}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent-teal px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-700"
                >
                  View Details <ArrowRight size={16} />
                </button>
              </div>
            ) : (
              <div className="mt-4 rounded-xl border border-dashed border-[#d9d1c4] bg-slate-50 p-4">
                <p className="text-sm text-slate-600">Select a property marker or click anywhere on the map to inspect a destination.</p>
              </div>
            )}
          </Card>

          <Card className="p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Bounding details</p>
            <div className="mt-4 space-y-3 text-sm text-slate-600">
              <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                <span>Latitude</span>
                <span className="min-w-0 break-words text-right font-semibold text-ink-900">{selectedLocation.lat.toFixed(4)}</span>
              </div>
              <div className="flex items-start justify-between gap-3 border-b border-[#f0ebdf] pb-2">
                <span>Longitude</span>
                <span className="min-w-0 break-words text-right font-semibold text-ink-900">{selectedLocation.lng.toFixed(4)}</span>
              </div>
              <div className="flex items-start justify-between gap-3">
                <span>Search context</span>
                <span className="min-w-0 break-words text-right font-semibold text-ink-900">{selectedLocation.label}</span>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </Card>
  );
}
