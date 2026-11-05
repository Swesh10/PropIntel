import React from "react";
import {
  ArrowRight,
  BedDouble,
  Building2,
  CalendarDays,
  Home,
  Layers,
  MapPin,
  Ruler,
  Sofa,
  Sparkles,
} from "lucide-react";
import { Card, SectionHeader, formatINR, formatPSF } from "./Shared.jsx";

const FEATURE_DETAILS = {
  bhk: {
    label: "BHK configuration",
    icon: BedDouble,
    why: (value) => `A ${value} BHK layout helps describe how the home may suit different household needs.`,
  },
  area_sqft: {
    label: "Property size",
    icon: Ruler,
    why: () => "The available living space is one of the details buyers can weigh when comparing homes.",
  },
  age_years: {
    label: "Property age",
    icon: CalendarDays,
    why: () => "The property's age gives context about how recently it was built.",
  },
  floor: {
    label: "Floor level",
    icon: Building2,
    why: () => "Floor level helps describe where the home sits within its building.",
  },
  total_floors: {
    label: "Building height",
    icon: Layers,
    why: () => "The number of floors helps describe the building this home is part of.",
  },
  amenities_count: {
    label: "Amenities",
    icon: Sparkles,
    why: (value) => `The amenities recorded for this property help describe the features available with this home.`,
  },
  city: {
    label: "Market zone",
    icon: MapPin,
    why: () => "The market zone gives the estimate its broader location context.",
  },
  locality: {
    label: "Locality",
    icon: MapPin,
    why: () => "The neighbourhood is one of the location details used in the estimate.",
  },
  property_type: {
    label: "Property type",
    icon: Home,
    why: (value) => `${value} describes the kind of home being valued.`,
  },
  furnishing: {
    label: "Furnishing",
    icon: Sofa,
    why: (value) => `Furnishing status helps describe how much is already in place for a new owner.`,
  },
};

const FALLBACK_DETAILS = {
  label: "Property detail",
  icon: Home,
  why: () => "This detail is one part of the information used to estimate the property's value.",
};

const MAX_FACTORS = 5;
const IMPORTANCE_SCALE = 10;

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function displayFeatureValue(feature, value) {
  if (feature === "area_sqft") {
    const area = numericValue(value);
    return area === null ? null : `${area.toLocaleString("en-IN")} sq. ft.`;
  }
  if (feature === "bhk") return `${value} BHK`;
  if (feature === "age_years") {
    const age = numericValue(value);
    return age === null ? null : `${age} ${age === 1 ? "year" : "years"}`;
  }
  if (feature === "floor") {
    const floor = numericValue(value);
    if (floor === null) return null;
    return floor === 0 ? "Ground floor" : `Floor ${floor}`;
  }
  if (feature === "total_floors") {
    return `${value} ${numericValue(value) === 1 ? "floor" : "floors"}`;
  }
  if (feature === "amenities_count") {
    return `${value} ${numericValue(value) === 1 ? "amenity" : "amenities"}`;
  }
  return value === null || value === undefined || value === "" ? null : String(value);
}

function getReliableFactors(explanation, prediction, input) {
  const contributions = explanation?.contributions;
  const baseValue = numericValue(explanation?.base_value);
  const explainedPrice = numericValue(explanation?.predicted_value);
  const predictedPrice = numericValue(prediction?.predicted_price);

  if (
    explanation?.output_scale !== "INR" ||
    !Array.isArray(contributions) ||
    !contributions.length ||
    baseValue === null ||
    explainedPrice === null ||
    predictedPrice === null
  ) {
    return [];
  }

  const items = contributions.map((item) => ({
    ...item,
    impact_rupees: numericValue(item?.impact_rupees),
    value: item?.value ?? input?.[item?.raw_feature],
  }));
  if (
    items.some(
      (item) =>
        !item.raw_feature ||
        item.impact_rupees === null ||
        displayFeatureValue(item.raw_feature, item.value) === null
    )
  ) {
    return [];
  }

  const contributionTotal = items.reduce((total, item) => total + item.impact_rupees, 0);
  if (
    Math.abs(baseValue + contributionTotal - explainedPrice) > 0.01 ||
    Math.abs(explainedPrice - predictedPrice) > 0.51
  ) {
    return [];
  }

  const factors = items
    .map((item) => ({
      ...item,
      details: FEATURE_DETAILS[item.raw_feature] || FALLBACK_DETAILS,
    }))
    .sort((first, second) => Math.abs(second.impact_rupees) - Math.abs(first.impact_rupees))
    .slice(0, MAX_FACTORS);

  const displayedImportanceTotal = factors.reduce(
    (total, item) => total + Math.abs(item.impact_rupees),
    0
  );
  if (displayedImportanceTotal === 0) return [];

  const shares = factors.map((item, index) => {
    const exactTenths =
      (Math.abs(item.impact_rupees) / displayedImportanceTotal) * 100 * IMPORTANCE_SCALE;
    const floorTenths = Math.floor(exactTenths);
    return {
      index,
      tenths: floorTenths,
      remainder: exactTenths - floorTenths,
    };
  });
  let tenthsLeft =
    100 * IMPORTANCE_SCALE - shares.reduce((total, item) => total + item.tenths, 0);
  const byRemainder = [...shares].sort((first, second) => second.remainder - first.remainder);
  for (let index = 0; index < tenthsLeft; index += 1) {
    byRemainder[index % byRemainder.length].tenths += 1;
  }

  return factors.map((item, index) => ({
    ...item,
    importance_pct: shares.find((share) => share.index === index).tenths / IMPORTANCE_SCALE,
  }));
}

function FactorCard({ item, index }) {
  const { label, icon: Icon, why } = item.details;
  return (
    <li className="rounded-xl border border-slate-200/80 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-50 text-ink-600">
          <Icon size={19} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold text-ink-900">{label}</h3>
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-semibold text-emerald-800">
              {displayFeatureValue(item.raw_feature, item.value)}
            </span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <div
              className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-100"
              role="img"
              aria-label={`${label}: ${item.importance_pct.toFixed(1)}% of the displayed explanation`}
            >
              <div
                className="h-full rounded-full bg-accent-teal"
                style={{ width: `${item.importance_pct}%` }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-sm font-bold tabular-nums text-ink-900">
              {item.importance_pct.toFixed(1)}%
            </span>
          </div>
          <p className="mt-3 text-sm leading-6 text-ink-600">{why(item.value)}</p>
        </div>
        <span className="hidden text-xs font-medium text-ink-300 sm:block" aria-hidden="true">
          {String(index + 1).padStart(2, "0")}
        </span>
      </div>
    </li>
  );
}

function estimateDescription(price) {
  return `Based on similar property listings, your property is estimated to be worth approximately ${formatINR(price)}. This is an estimate, not a confirmed sale price.`;
}

function overallExplanation(factors) {
  if (!factors.length) {
    return "The estimate is based on the property details together. A reliable feature-by-feature explanation is not available for this prediction.";
  }

  const leading = factors.slice(0, 3);
  const names = leading.map((item) => item.details.label.toLowerCase());
  const factorList = names.length > 1
    ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
    : names[0];
  return `For this property, ${factorList} account for the largest shares of the explanation. PropIntel considers these details together when estimating the value; no single feature determines the price on its own.`;
}

export default function ExplainableAI({ initialPrediction, onNavigateToPredict }) {
  if (!initialPrediction) {
    return (
      <div>
        <SectionHeader
          title="Why is your property worth this much?"
          subtitle="See the estimate and the property details behind it."
        />
        <Card className="flex flex-col items-center justify-center gap-5 p-12 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-50">
            <Home size={28} className="text-accent-teal" />
          </div>
          <div>
            <p className="font-display text-xl font-bold text-ink-900">No estimate to explain yet</p>
            <p className="mt-2 max-w-sm text-sm text-ink-600">
              Estimate a property first to see the details behind its price.
            </p>
          </div>
          {onNavigateToPredict && (
            <button onClick={onNavigateToPredict} className="button-primary">
              Estimate a property <ArrowRight size={16} />
            </button>
          )}
        </Card>
      </div>
    );
  }

  const { prediction = {}, explanation = {}, input = {} } = initialPrediction;
  const estimatedPrice =
    numericValue(prediction.predicted_price) ?? numericValue(explanation.predicted_value);
  const area = numericValue(input.area_sqft);
  const pricePerSqft =
    numericValue(prediction.predicted_price_per_sqft) ??
    (estimatedPrice !== null && area > 0 ? estimatedPrice / area : null);
  const factors = getReliableFactors(explanation, prediction, input);

  return (
    <div>
      <SectionHeader
        title="Why is your property worth this much?"
        subtitle="A clear explanation of your estimated value, based on the details of your property."
      />

      <Card className="mb-5 overflow-hidden p-0">
        <div className="h-1.5 bg-accent-teal" />
        <div className="p-5 sm:p-7">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-accent-teal">
              Your property&apos;s estimated market value
            </p>
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
              AI estimated price
            </span>
          </div>
          <h2 className="mt-2 font-display text-3xl font-bold tracking-tight text-ink-900 sm:text-4xl">
            {estimatedPrice === null ? "Estimate unavailable" : formatINR(estimatedPrice)}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-600">
            {estimatedPrice === null
              ? "A price could not be read from this prediction. Please run the estimate again."
              : estimateDescription(estimatedPrice)}
          </p>
          {pricePerSqft !== null && (
            <p className="mt-3 text-xs font-medium text-ink-400">
              {formatPSF(pricePerSqft)} <span aria-hidden="true">·</span> {propertyContext(input)}
            </p>
          )}
          {prediction.is_reliable === false && (
            <p role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-5 text-amber-900">
              Some property details have limited or unusual examples in the available listings. Treat this estimate with extra care.
            </p>
          )}
        </div>
      </Card>

      <Card className="p-5 sm:p-7">
        <div>
          <h2 className="font-display text-xl font-bold text-ink-900">
            How much does each factor matter to your property&apos;s price?
          </h2>
          <p className="mt-1 text-sm leading-5 text-ink-500">
            Relative importance for this prediction, based on the model&apos;s SHAP explanation.
          </p>
        </div>

        {factors.length > 0 ? (
          <ul className="mt-5 space-y-3">
            {factors.map((item, index) => (
              <FactorCard key={item.raw_feature} item={item} index={index} />
            ))}
          </ul>
        ) : (
          <div role="status" className="mt-5 rounded-xl border border-slate-100 bg-slate-50 p-5 text-sm leading-6 text-ink-600">
            The estimated price is available, but a reliable feature-by-feature explanation was not provided for this prediction.
          </div>
        )}

        <section className="mt-6 rounded-xl bg-slate-50 p-4 sm:p-5">
          <h2 className="font-display text-lg font-bold text-ink-900">
            So, why is your property valued at this price?
          </h2>
          <p className="mt-2 text-sm leading-6 text-ink-600">
            {overallExplanation(factors)}
          </p>
        </section>
        <p className="mt-4 text-xs leading-5 text-ink-500">
          These percentages show how much each property detail contributes to the AI&apos;s prediction explanation. They do not represent a percentage increase or decrease in your property&apos;s actual market price.
        </p>
      </Card>
    </div>
  );
}

function propertyContext(input) {
  return [
    input.bhk && `${input.bhk} BHK`,
    input.property_type,
    input.locality,
    input.city,
  ].filter(Boolean).join(" · ");
}
