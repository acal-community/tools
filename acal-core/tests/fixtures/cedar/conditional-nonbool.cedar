permit (principal, action, resource)
when { (if principal.vip then "gold" else "silver") == principal.tier };
