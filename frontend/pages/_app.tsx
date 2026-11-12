import type {AppProps} from 'next/app';
import Head from 'next/head';
import {useEffect,useState} from 'react';
import '../shop/shop.css';

export default function ShoppingApplication({Component,pageProps}:AppProps) {
  return <><Head><meta name="robots" content="noindex, nofollow"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/></Head>
    <ShoppingSession Component={Component} pageProps={pageProps} key={pageProps.sessionId??'outside'}/></>;
}

// Search text belongs to the shopping visit; page measurements still reset per view.
function ShoppingSession({Component,pageProps}:Pick<AppProps,'Component'|'pageProps'>) {
  const [searchQuery,setSearchQuery]=useState(pageProps.result?.query??'');
  useEffect(()=>{if(pageProps.result)setSearchQuery(pageProps.result.query);},[pageProps.result?.query]);
  return <Component {...pageProps} key={pageProps.viewId} searchQuery={searchQuery} onSearchQueryChange={setSearchQuery}/>;
}
