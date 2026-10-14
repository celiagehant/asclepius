import type { ProfileData } from "../api/client";

// One topic per screen. Every question except age offers "prefer not to say" and explains why it is asked.
export type StepId = "who" | "age" | "sex" | "pregnancy" | "medications" | "allergies" | "conditions" | "family" | "habits" | "concern" | "review";

export const STEP_INFO: Record<StepId, { title: string; why: string }> = {
  who: { title: "Who is this profile for?", why: "A minor never creates their own account; a parent or guardian adds a profile for them. One account can hold several people." },
  age: { title: "Age or date of birth", why: "Normal lab ranges change with age, and children are reviewed with pediatric ranges." },
  sex: { title: "Sex assigned at birth", why: "Lab reference ranges (for example hemoglobin and creatinine) depend on sex assigned at birth." },
  pregnancy: { title: "Pregnancy or breastfeeding", why: "Pregnancy and breastfeeding change normal ranges and which medicines are safe." },
  medications: { title: "Current medications and supplements", why: "The pharmacist agent checks for duplicates and interactions across all your doctors." },
  allergies: { title: "Allergies", why: "Allergies matter whenever a doctor considers a medicine or test." },
  conditions: { title: "Known conditions and past surgeries", why: "Existing conditions change what a result means and which findings connect." },
  family: { title: "Family history", why: "Family history changes which findings deserve a closer look." },
  habits: { title: "Tobacco and alcohol", why: "Both affect many lab results, medicines and risks." },
  concern: { title: "What worries you today?", why: "This tells the panel what to focus on." },
  review: { title: "Review your answers", why: "You can change any answer now or later from your profile." },
};

export const CONDITIONS = ["High blood pressure", "Diabetes", "High cholesterol", "Heart disease", "Asthma or COPD", "Kidney disease",
  "Liver disease", "Thyroid condition", "Autoimmune condition", "Anemia", "Depression or anxiety", "Migraine"];
export const FAMILY = ["Heart disease", "Diabetes", "Autoimmune conditions", "Cancer"];

export function ageOf(p: Pick<ProfileData, "date_of_birth" | "age_years">): number | null {
  if (p.date_of_birth) {
    const b = new Date(p.date_of_birth + "T00:00:00");
    if (isNaN(b.getTime())) return null;
    const t = new Date();
    return t.getFullYear() - b.getFullYear() - (t.getMonth() < b.getMonth() || (t.getMonth() === b.getMonth() && t.getDate() < b.getDate()) ? 1 : 0);
  }
  return p.age_years ?? null;
}

export function pregnancyApplies(p: ProfileData): boolean {
  const age = ageOf(p);
  return p.sex_at_birth !== "male" && age !== null && age >= 10 && age <= 55;
}

export function stepsFor(p: ProfileData): StepId[] {
  const all: StepId[] = ["who", "age", "sex", "pregnancy", "medications", "allergies", "conditions", "family", "habits", "concern", "review"];
  // Keep the pregnancy screen in the count until it is ruled out, so the progress bar doesn't jump.
  const age = ageOf(p);
  const ruledOut = p.sex_at_birth === "male" || (age !== null && (age < 10 || age > 55));
  return all.filter((s) => s !== "pregnancy" || !ruledOut);
}

export function emptyProfile(forWhom: "self" | "care" = "self"): ProfileData {
  return {
    for_whom: forWhom, name: "", relationship: null, date_of_birth: null, age_years: null, sex_at_birth: "" as ProfileData["sex_at_birth"],
    gender_identity: "", pregnancy: null, medications_status: "listed", medications: [], allergies_status: "listed", allergies: [],
    conditions_status: "listed", conditions: [], conditions_other: "", surgeries: "", family_status: "listed", family_history: [],
    family_other: "", tobacco: "" as ProfileData["tobacco"], alcohol: "" as ProfileData["alcohol"], main_concern: "", main_concern_withheld: false, doctors: [],
  };
}

export const LABELS: Record<string, string> = {
  self: "Myself", care: "Someone in my care", female: "Female", male: "Male", intersex: "Intersex", prefer_not_to_say: "Prefer not to say",
  pregnant: "Pregnant", breastfeeding: "Breastfeeding", neither: "Neither", not_sure: "Not sure", listed: "Yes", none: "None",
  none_known: "None that I know of", never: "Never", former: "Used to", current: "Currently", occasionally: "Occasionally", weekly: "Weekly",
  most_days: "Most days",
};
