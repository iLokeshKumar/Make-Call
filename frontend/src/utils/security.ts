export const maskEmail = (email: string) => {
    if (!email) return "••••@••••.•••";
    const [name, domain] = email.split("@");
    if (!name || !domain) return "••••@••••.•••";
    return `${name[0]}••••@${domain}`;
};

export const maskPhone = (phone: string) => {
    if (!phone) return "•••••••000";
    return `•••••••${phone.slice(-2)}`;
};