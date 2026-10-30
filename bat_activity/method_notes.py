"""Shared calculation notes for on-screen and exported results."""
METHOD_NOTE = (
    "Results combine the selected survey periods. Version 1 uses assumed_full: intended recording hours, not verified operational effort. Failures and interruptions may understate rates. Version 1 assumes all reviewed data for the selected nights have been supplied; missing records can understate activity and affect comparisons. Blocking record errors remain excluded. Legacy full-coverage nights are also supported; legacy partial, failed and unknown nights are excluded. Zero-contact nights are included under these assumptions. Activity rates describe "
    "detector contacts per recording hour, not numbers of individual bats. Mean is the arithmetic "
    "mean of nightly rates. Quartiles use linear interpolation; IQR = Q3 - Q1. Boxplot whiskers "
    "extend to the most extreme observations within 1.5 IQR of the quartiles; other values are plotted individually."
    " Surveys 1-8 are the selected date blocks in chronological order, not blocks inferred from detections."
    " The site-wide stacked chart sums species into broad groups within each eligible detector-night,"
    " divides by that detector-night's recording hours (intended for assumed_full), then takes the arithmetic mean across eligible"
    " detector-nights in each survey. It is not a sum of detector means or pooled contacts/hours."
    " Each eligible detector-night has equal weight; unequal coverage can change the contribution of"
    " locations between surveys. The survey key records the effort and original date ranges."
    " Grouping is for the stacked chart only; original identifications are retained in other outputs."
)
