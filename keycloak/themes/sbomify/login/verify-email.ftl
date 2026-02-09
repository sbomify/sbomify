<#import "template.ftl" as layout>
<#import "components.ftl" as components>
<@layout.registrationLayout; section>
    <#if section = "header">
        <!-- Header is handled in the info panel -->
    <#elseif section = "form">
        <@components.emailVerificationContent />
    </#if>
</@layout.registrationLayout>
