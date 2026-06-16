"""Allowed categorical values for structured technology intelligence output."""

MAIN_CATEGORIES = (
    "Carbon Capture",
    "Supplementary Cementitious Material",
    "Alternative SCM",
    "Alternative Cementitious Material",
    "Aggregate Technology",
    "Concrete Design",
    "Structural Design",
    "Other",
    "Not Reported",
)

DEPLOYMENT_STAGES = (
    "Laboratory",
    "Pilot",
    "Demonstration",
    "Not Reported",
)

PROJECT_STAGES = (
    "Pilot",
    "Demonstration",
    "Not Reported",
)

COMPANY_ROLES = (
    "Developer",
    "Deploying company",
    "Cement/concrete producer partner",
    "Research institution",
    "Investor/funder",
    "Other",
    "Not Reported",
)

CONFIDENCE_LEVELS = (
    "High",
    "Medium",
    "Low",
    "Not Reported",
)

CCS_SUBCATEGORIES = (
    "Post-combustion capture",
    "Oxyfuel combustion",
    "Direct separation",
    "Calcium looping",
    "Membrane separation",
    "Adsorption",
    "Mineralization/carbonation",
    "Direct air capture linked to concrete/cement",
    "Other",
    "Not Reported",
)

MAIN_CATEGORY_ALIASES: dict[str, str] = {
    "carbon capture": "Carbon Capture",
    "ccs": "Carbon Capture",
    "scm": "Supplementary Cementitious Material",
    "supplementary cementitious material (scm)": "Supplementary Cementitious Material",
    "supplementary cementitious materials": "Supplementary Cementitious Material",
    "alternative scm": "Alternative SCM",
    "alternative cement": "Alternative Cementitious Material",
    "alternative cementitious material": "Alternative Cementitious Material",
    "acm": "Alternative Cementitious Material",
    "aggregate": "Aggregate Technology",
    "concrete design": "Concrete Design",
    "structural design": "Structural Design",
    "unknown": "Not Reported",
    "commercial": "Not Reported",
}

DEPLOYMENT_STAGE_ALIASES: dict[str, str] = {
    "lab": "Laboratory",
    "laboratory": "Laboratory",
    "pilot": "Pilot",
    "pilot scale": "Pilot",
    "demonstration": "Demonstration",
    "demo": "Demonstration",
    "demonstration scale": "Demonstration",
    "commercial": "Not Reported",
    "unknown": "Not Reported",
}

CCS_SUBCATEGORY_ALIASES: dict[str, str] = {
    "post combustion": "Post-combustion capture",
    "post-combustion": "Post-combustion capture",
    "post combustion capture": "Post-combustion capture",
    "oxyfuel": "Oxyfuel combustion",
    "oxy-fuel": "Oxyfuel combustion",
    "oxy fuel": "Oxyfuel combustion",
    "direct separation": "Direct separation",
    "calcium looping": "Calcium looping",
    "membrane": "Membrane separation",
    "adsorption": "Adsorption",
    "mineralization": "Mineralization/carbonation",
    "carbonation": "Mineralization/carbonation",
    "dac": "Direct air capture linked to concrete/cement",
    "direct air capture": "Direct air capture linked to concrete/cement",
}

COMPANY_ROLE_ALIASES: dict[str, str] = {
    "developer": "Developer",
    "deploying company": "Deploying company",
    "deployer": "Deploying company",
    "cement partner": "Cement/concrete producer partner",
    "cement/concrete producer partner": "Cement/concrete producer partner",
    "producer partner": "Cement/concrete producer partner",
    "research institution": "Research institution",
    "university": "Research institution",
    "investor": "Investor/funder",
    "funder": "Investor/funder",
    "investor/funder": "Investor/funder",
}

INTELLIGENCE_OPTIONS = {
    "main_categories": list(MAIN_CATEGORIES),
    "ccs_subcategories": list(CCS_SUBCATEGORIES),
    "deployment_stages": list(DEPLOYMENT_STAGES),
    "project_stages": list(PROJECT_STAGES),
    "company_roles": list(COMPANY_ROLES),
    "confidence_levels": list(CONFIDENCE_LEVELS),
}
