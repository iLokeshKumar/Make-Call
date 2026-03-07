/**
 * Masks an email address for security.
 * Example: "john.doe@example.com" -> "j••••@example.com"
 */
export const maskEmail = (email: string) => {
    if (!email) return "••••@••••.•••";
    const [name, domain] = email.split("@");
    if (!name || !domain) return "••••@••••.•••";
    return `${name[0]}••••@${domain}`;
};

/**
 * Masks a phone number for security.
 * Example: "1234567890" -> "•••••••890"
 */
export const maskPhone = (phone: string) => {
    if (!phone) return "•••••••000";
    return `•••••••${phone.slice(-3)}`;
};
