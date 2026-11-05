import React from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatPSF } from "./Shared.jsx";

const BAR_COLORS = ["#10A889", "#46B99F", "#7CCDB9", "#F59E0B", "#5B8DEF", "#79A9F2", "#A2C2F7", "#7DAA9E"];

export default function DashboardCharts({ data, type }) {
  if (type === "bedrooms") {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke="#E8EEF3" />
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="bhk" tick={{ fontSize: 12, fill: "#64748B" }} axisLine={false} tickLine={false} width={68} />
          <Tooltip formatter={(value) => [Number(value).toLocaleString("en-IN"), "Listings"]} contentStyle={{ borderRadius: 10, border: "1px solid #E2E8F0", fontSize: 12 }} />
          <Bar dataKey="count" fill="#10A889" radius={[0, 6, 6, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 48 }}>
        <CartesianGrid vertical={false} stroke="#E8EEF3" />
        <XAxis dataKey="city" angle={-30} textAnchor="end" minTickGap={12} tick={{ fontSize: 10, fill: "#64748B" }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fontSize: 10, fill: "#64748B" }} axisLine={false} tickLine={false} tickFormatter={(value) => `₹${Math.round(value / 1000)}k`} />
        <Tooltip formatter={(value) => [formatPSF(value), "Average"]} contentStyle={{ borderRadius: 10, border: "1px solid #E2E8F0", fontSize: 12, boxShadow: "0 8px 24px rgba(18,48,74,0.08)" }} />
        <Bar dataKey="psf" radius={[6, 6, 0, 0]} maxBarSize={42}>
          {data.map((entry, index) => <Cell key={entry.city} fill={BAR_COLORS[index % BAR_COLORS.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
